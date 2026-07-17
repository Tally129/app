"""
Dashboard stats + Admin audit/user/session routes.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request

from audit import get_client_ip, log_audit, verify_audit_chain
from auth_utils import hash_password
from deps import _strip_id, _resolve_self_client, api, db, get_current_user, require_roles, to_user_out
from models import AuditLogOut, UserCreate, UserOut, new_id
from permissions import P, require_permission
from sessions import list_active_sessions_sanitized, revoke_all_user_sessions, revoke_family


# =================== DASHBOARD ===================
@api.get("/dashboard/stats")
async def dashboard_stats(user=Depends(get_current_user)):
    role = user["role"]
    if role in ("admin", "staff"):
        return {
            "role": role,
            "clients": await db.clients.count_documents({}),
            "notes": await db.visit_notes.count_documents({}),
            "files": await db.files.count_documents({}),
            "appointments_requested": await db.appointment_requests.count_documents({}),
            "users": await db.users.count_documents({}),
            "audit_events": await db.audit_logs.count_documents({}),
        }
    if role == "practitioner":
        return {
            "role": role,
            "my_patients": await db.clients.count_documents({"assigned_practitioner_id": user["id"]}),
            "total_clients": await db.clients.count_documents({}),
            "my_notes": await db.visit_notes.count_documents({"practitioner_id": user["id"]}),
        }
    self_client = await _resolve_self_client(user)
    if not self_client:
        return {"role": role}
    return {
        "role": role,
        "client_id": self_client["id"],
        "intake_completed": self_client.get("intake_completed", False),
        "notes": await db.visit_notes.count_documents({"client_id": self_client["id"]}),
        "files": await db.files.count_documents({"client_id": self_client["id"]}),
    }


# =================== ADMIN ===================
@api.get("/admin/audit", response_model=List[AuditLogOut])
async def admin_audit(limit: int = 100, user_id: Optional[str] = None, action: Optional[str] = None,
                      user=Depends(require_roles("admin"))):
    q = {}
    if user_id:
        q["user_id"] = user_id
    if action:
        q["action"] = action
    items = await db.audit_logs.find(q).sort("ts", -1).to_list(min(limit, 500))
    return [_strip_id(i) for i in items]


@api.get("/admin/users", response_model=List[UserOut])
async def admin_users(user=Depends(require_roles("admin"))):
    items = await db.users.find().sort("created_at", -1).to_list(5000)
    return [to_user_out(_strip_id(i)) for i in items]


@api.post("/admin/users", response_model=UserOut)
async def admin_create_user(payload: UserCreate, request: Request, user=Depends(require_roles("admin"))):
    if payload.role not in ("admin", "practitioner", "staff", "client"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if await db.users.find_one({"email": payload.email.lower()}):
        raise HTTPException(status_code=409, detail="Email already registered")
    doc = {
        "id": new_id(),
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "full_name": payload.full_name,
        "phone": payload.phone,
        "role": payload.role,
        "mfa_enabled": False,
        "mfa_secret": None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }
    await db.users.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "admin.create_user",
                    resource_type="user", resource_id=doc["id"],
                    metadata={"role": payload.role},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return to_user_out(doc)


@api.put("/admin/users/{user_id}/role", response_model=UserOut)
async def admin_update_role(user_id: str, body: dict, request: Request, user=Depends(require_roles("admin"))):
    role = (body or {}).get("role")
    if role not in ("admin", "practitioner", "staff", "client"):
        raise HTTPException(status_code=400, detail="Invalid role")
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one({"id": user_id}, {"$set": {"role": role}})
    # Role change is a security event — bump session_version + revoke every family.
    await db.users.update_one({"id": user_id},
                              {"$inc": {"session_version": 1}})
    revoked = await revoke_all_user_sessions(user_id, "role_change")
    await log_audit(db, user["id"], user["email"], "admin.update_role",
                    resource_type="user", resource_id=user_id, metadata={"role": role, **revoked},
                    severity="high", outcome="success",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    target = await db.users.find_one({"id": user_id})
    return to_user_out(target)


@api.put("/admin/users/{user_id}/active")
async def admin_toggle_active(user_id: str, body: dict, request: Request,
                              user=Depends(require_permission(P.USER_DEACTIVATE))):
    active = bool((body or {}).get("is_active", False))
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one({"id": user_id}, {"$set": {"is_active": active}})
    # Deactivation is a security event — revoke all sessions immediately.
    revoked = None
    if not active:
        await db.users.update_one({"id": user_id}, {"$inc": {"session_version": 1}})
        revoked = await revoke_all_user_sessions(user_id, "user_deactivated")
    await log_audit(db, user["id"], user["email"], "admin.deactivate_user" if not active else "admin.activate_user",
                    resource_type="user", resource_id=user_id,
                    severity="high", outcome="success",
                    metadata={"is_active": active, **(revoked or {})},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "is_active": active}


# =================== SESSION EXPLORER ===================
@api.get("/admin/sessions")
async def admin_list_sessions(user_id: Optional[str] = None, limit: int = 200,
                              user=Depends(require_permission(P.SESSION_LIST_ANY))):
    """List active workforce/user sessions. `user_id` optional filter."""
    q = {"revoked_at": None}
    if user_id:
        q["user_id"] = user_id
    rows = await db.user_sessions.find(q).sort("last_used_at", -1).to_list(min(max(1, limit), 500))
    users = {u["id"]: u async for u in db.users.find(
        {"id": {"$in": list({r["user_id"] for r in rows if r.get("user_id")})}},
        {"id": 1, "email": 1, "full_name": 1, "role": 1},
    )}
    out = []
    for r in rows:
        u = users.get(r.get("user_id")) or {}
        out.append({
            "id": r["id"],
            "user_id": r.get("user_id"),
            "email": u.get("email"),
            "full_name": u.get("full_name"),
            "role": u.get("role"),
            "created_at": r.get("created_at"),
            "last_used_at": r.get("last_used_at"),
            "absolute_expires_at": r.get("absolute_expires_at"),
            "idle_timeout_minutes": r.get("idle_timeout_minutes"),
            "ip_first": r.get("ip_first"),
            "ip_last": r.get("ip_last"),
            # Truncated UA to avoid over-broad device fingerprinting.
            "user_agent": (r.get("user_agent") or "")[:120],
            "mfa_satisfied_at": r.get("mfa_satisfied_at"),
        })
    return out


@api.post("/admin/sessions/{session_id}/revoke")
async def admin_revoke_session(session_id: str, request: Request,
                               user=Depends(require_permission(P.SESSION_REVOKE_ANY))):
    row = await db.user_sessions.find_one({"id": session_id})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.get("revoked_at"):
        return {"ok": True, "already_revoked": True}
    now = datetime.now(timezone.utc)
    await db.user_sessions.update_one(
        {"id": session_id, "revoked_at": None},
        {"$set": {"revoked_at": now, "revoke_reason": "admin_revoke"}},
    )
    if row.get("family_id"):
        await revoke_family(row["family_id"], "admin_revoke")
    await log_audit(db, user["id"], user["email"], "admin.session_revoke",
                    resource_type="user_session", resource_id=session_id,
                    severity="high", outcome="success",
                    metadata={"target_user_id": row.get("user_id")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/admin/users/{target_user_id}/revoke-all-sessions")
async def admin_revoke_all_sessions(target_user_id: str, request: Request,
                                    user=Depends(require_permission(P.SESSION_REVOKE_ANY))):
    target = await db.users.find_one({"id": target_user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    result = await revoke_all_user_sessions(target_user_id, "admin_revoke_all")
    await log_audit(db, user["id"], user["email"], "admin.session_revoke_all",
                    resource_type="user", resource_id=target_user_id,
                    severity="high", outcome="success",
                    metadata=result,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, **result}


@api.get("/admin/audit/verify-chain")
async def admin_verify_audit_chain(limit: int = 5000,
                                   user=Depends(require_permission(P.AUDIT_READ))):
    return await verify_audit_chain(db, limit=limit)


