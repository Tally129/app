"""
Clinical delegation grant / list / revoke endpoints.

Providers can grant scoped, time-limited edit rights to Admin or Medical
Assistant users. Delegates use the resulting record to unlock draft editing
on SOAP notes, treatment plans, assessments, and forms/protocols.

Route surface
    POST   /api/delegations              (provider)
    GET    /api/delegations              (workforce: mine granted OR received)
    DELETE /api/delegations/{id}         (grantor OR admin)
    GET    /api/delegations/effective    (delegate: is a client_id editable?)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from audit import get_client_ip, log_audit
from delegations import (
    DEFAULT_TTL, ELIGIBLE_DELEGATE_ROLES, MAX_TTL,
    has_active_delegation,
)
from deps import _strip_id, api, db, get_current_user, require_roles
from models import new_id


class DelegationIn(BaseModel):
    delegate_id: str
    client_id: Optional[str] = None       # None = blanket
    scope: str = "documentation"
    ttl_minutes: int = Field(default=1440, ge=15, le=int(MAX_TTL.total_seconds() // 60))
    note: Optional[str] = None


@api.post("/delegations")
async def create_delegation(payload: DelegationIn, request: Request,
                            user=Depends(require_roles("practitioner"))):
    delegate = await db.users.find_one({"id": payload.delegate_id})
    if not delegate:
        raise HTTPException(status_code=404, detail="Delegate user not found")
    if delegate.get("role") not in ELIGIBLE_DELEGATE_ROLES:
        raise HTTPException(status_code=400, detail={
            "code": "delegate_role_ineligible",
            "message": "Only Admin or Medical Assistant users may be delegates.",
            "eligible_roles": sorted(ELIGIBLE_DELEGATE_ROLES),
        })
    if payload.client_id:
        client = await db.clients.find_one({"id": payload.client_id})
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
    if payload.scope != "documentation":
        raise HTTPException(status_code=400, detail="Only 'documentation' scope is supported currently")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=int(payload.ttl_minutes))
    doc = {
        "id": new_id(),
        "provider_id": user["id"],
        "provider_name": user.get("full_name", ""),
        "delegate_id": delegate["id"],
        "delegate_name": delegate.get("full_name", ""),
        "delegate_role": delegate.get("role"),
        "client_id": payload.client_id,
        "scope": payload.scope,
        "note": (payload.note or "").strip()[:400] or None,
        "created_at": now,
        "expires_at": expires_at,
        "revoked_at": None,
    }
    await db.clinical_delegations.insert_one(doc)
    await log_audit(
        db, user["id"], user["email"], "delegation.grant",
        resource_type="delegation", resource_id=doc["id"],
        severity="high", outcome="success",
        metadata={
            "delegate_id": delegate["id"],
            "delegate_role": delegate.get("role"),
            "client_id": payload.client_id,
            "expires_at": expires_at.isoformat(),
        },
        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    return _strip_id(doc)


@api.get("/delegations")
async def list_delegations(role_scope: str = Query("all"),
                           user=Depends(get_current_user)):
    """List delegations relevant to me. `role_scope` = granted | received | all."""
    if user.get("role") == "client":
        raise HTTPException(status_code=403, detail="Forbidden")
    now = datetime.now(timezone.utc)
    q: dict = {}
    if role_scope == "granted":
        q = {"provider_id": user["id"]}
    elif role_scope == "received":
        q = {"delegate_id": user["id"]}
    else:
        q = {"$or": [{"provider_id": user["id"]}, {"delegate_id": user["id"]}]}
    rows = await db.clinical_delegations.find(q).sort("created_at", -1).to_list(200)
    out = []
    for r in rows:
        r = _strip_id(r)
        r["is_active"] = (
            r.get("revoked_at") is None
            and (r.get("expires_at") and r["expires_at"] > now)
        )
        out.append(r)
    return out


@api.delete("/delegations/{delegation_id}")
async def revoke_delegation(delegation_id: str, request: Request,
                            user=Depends(get_current_user)):
    d = await db.clinical_delegations.find_one({"id": delegation_id})
    if not d:
        raise HTTPException(status_code=404, detail="Delegation not found")
    if user.get("role") not in ("admin", "practitioner") or (
        user.get("role") == "practitioner" and d.get("provider_id") != user["id"]
    ):
        raise HTTPException(status_code=403, detail="Only the granting provider or an admin can revoke")
    if d.get("revoked_at"):
        return {"ok": True, "already_revoked": True}
    now = datetime.now(timezone.utc)
    await db.clinical_delegations.update_one(
        {"id": delegation_id, "revoked_at": None},
        {"$set": {"revoked_at": now}},
    )
    await log_audit(
        db, user["id"], user["email"], "delegation.revoke",
        resource_type="delegation", resource_id=delegation_id,
        severity="high", outcome="success",
        metadata={"delegate_id": d.get("delegate_id"),
                  "client_id": d.get("client_id")},
        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    return {"ok": True}


@api.get("/delegations/effective")
async def effective_delegation(client_id: Optional[str] = None,
                               user=Depends(get_current_user)):
    """Called by clinical UI to decide whether to render editing controls."""
    role = user.get("role")
    if role == "practitioner":
        return {"can_edit_draft": True, "reason": "provider", "delegation": None}
    if role not in ELIGIBLE_DELEGATE_ROLES:
        return {"can_edit_draft": False, "reason": "role_ineligible", "delegation": None}
    d = await has_active_delegation(user, client_id)
    if d:
        return {"can_edit_draft": True, "reason": "delegated",
                "delegation": _strip_id(d)}
    return {"can_edit_draft": False, "reason": "no_delegation", "delegation": None}
