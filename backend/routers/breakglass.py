"""
Break-glass emergency access — workforce-only, target-scoped, MFA-recent,
maximum 60-minute duration, no bulk export, no deletion, high-severity
audit trail on activation, use, and expiry.

Endpoints
---------
POST /api/breakglass/activate       — activate an emergency session
GET  /api/breakglass/active         — list *your* active break-glass sessions
POST /api/breakglass/{id}/revoke    — revoke a specific break-glass session
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from audit import log_audit, get_client_ip
from deps import WORKFORCE_ROLES, api, db, require_workforce_mfa
from models import new_id
from permissions import P, require_permission

MAX_BREAKGLASS_MINUTES = 60
MFA_RECENCY_MINUTES = 10


class BreakGlassActivateIn(BaseModel):
    target_client_id: Optional[str] = None
    target_resource_type: Optional[str] = Field(
        default=None,
        description="One of client, note, file — required if target_client_id is None",
    )
    target_resource_id: Optional[str] = None
    reason: str = Field(min_length=20, max_length=1000,
                        description="Written justification (min 20 chars)")
    duration_minutes: int = Field(default=30, ge=1, le=MAX_BREAKGLASS_MINUTES)


@api.post("/breakglass/activate")
async def breakglass_activate(payload: BreakGlassActivateIn, request: Request,
                              user=Depends(require_permission(P.BREAKGLASS_ACTIVATE))):
    role = user.get("role") or ""
    if role not in WORKFORCE_ROLES:
        raise HTTPException(status_code=403, detail="Workforce accounts only")
    # MFA-recent check: the session must have satisfied MFA within the recency window.
    sess = user.get("_session") or {}
    mfa_at = sess.get("mfa_satisfied_at")
    now = datetime.now(timezone.utc)
    if not mfa_at:
        raise HTTPException(status_code=403, detail={"code": "mfa_reauth_required"})
    mfa_at_utc = mfa_at.replace(tzinfo=timezone.utc) if mfa_at.tzinfo is None else mfa_at
    if (now - mfa_at_utc) > timedelta(minutes=MFA_RECENCY_MINUTES):
        raise HTTPException(status_code=403, detail={
            "code": "mfa_recency_required",
            "message": f"Re-verify MFA within the last {MFA_RECENCY_MINUTES} minutes to activate break-glass.",
        })
    if not payload.target_client_id and not (payload.target_resource_type and payload.target_resource_id):
        raise HTTPException(status_code=400, detail="Must target either a client or a specific resource")

    row = {
        "id": new_id(),
        "user_id": user["id"],
        "user_email": user["email"],
        "role": role,
        "target_client_id": payload.target_client_id,
        "target_resource_type": payload.target_resource_type,
        "target_resource_id": payload.target_resource_id,
        "reason": payload.reason,
        "duration_minutes": payload.duration_minutes,
        "activated_at": now,
        "expires_at": now + timedelta(minutes=payload.duration_minutes),
        "revoked_at": None,
        "revoke_reason": None,
        "session_id": (user.get("_session") or {}).get("id"),
        "ip": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }
    await db.breakglass_sessions.insert_one(row)

    await log_audit(
        db, user["id"], user["email"], "breakglass.activate",
        resource_type="breakglass", resource_id=row["id"],
        severity="high", outcome="success",
        metadata={
            "target_client_id": payload.target_client_id,
            "target_resource_type": payload.target_resource_type,
            "target_resource_id": payload.target_resource_id,
            "duration_minutes": payload.duration_minutes,
            "reason_preview": payload.reason[:80],
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "id": row["id"],
        "activated_at": row["activated_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "duration_minutes": row["duration_minutes"],
        "target_client_id": row["target_client_id"],
        "target_resource_type": row["target_resource_type"],
        "target_resource_id": row["target_resource_id"],
    }


@api.get("/breakglass/active")
async def breakglass_active(user=Depends(require_workforce_mfa)):
    """Return *your* active break-glass sessions. Frontend uses this for the
    visible active-session indicator."""
    if user.get("role") not in WORKFORCE_ROLES:
        raise HTTPException(status_code=403, detail="Workforce accounts only")
    now = datetime.now(timezone.utc)
    rows = await db.breakglass_sessions.find({
        "user_id": user["id"],
        "expires_at": {"$gt": now},
        "revoked_at": None,
    }).to_list(50)
    out = []
    for r in rows:
        r.pop("_id", None)
        r.pop("user_agent", None)  # noise
        out.append(r)
    return out


@api.post("/breakglass/{bg_id}/revoke")
async def breakglass_revoke(bg_id: str, request: Request,
                            user=Depends(require_workforce_mfa)):
    if user.get("role") not in WORKFORCE_ROLES:
        raise HTTPException(status_code=403, detail="Workforce accounts only")
    row = await db.breakglass_sessions.find_one({"id": bg_id})
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    # Only the owner or an admin may revoke a break-glass session.
    if row["user_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    if row.get("revoked_at"):
        return {"ok": True, "already_revoked": True}
    now = datetime.now(timezone.utc)
    await db.breakglass_sessions.update_one(
        {"id": bg_id},
        {"$set": {"revoked_at": now, "revoke_reason": "manual"}},
    )
    await log_audit(
        db, user["id"], user["email"], "breakglass.revoke",
        resource_type="breakglass", resource_id=bg_id,
        severity="high", outcome="success",
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {"ok": True}
