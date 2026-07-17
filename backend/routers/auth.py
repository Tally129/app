"""
Authentication + Account routes.

Sprint 1 changes:
- Every login/register/refresh creates or rotates a server-side session (`user_sessions`).
- Access + refresh tokens now carry `iss`, `aud`, `jti`, `sid` (see auth_utils).
- Workforce accounts cannot disable MFA. `mfa_verify` marks the session's `mfa_satisfied_at`.
- `change_password` revokes all sessions and bumps `session_version`.
- New: `/auth/forgot-password`, `/auth/reset-password`, and a dev-only test helper
  (`/auth/dev/reset-token`) that is DISABLED when HIPAA_MODE=on.
"""
import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from audit import get_client_ip, log_audit
from auth_utils import (
    decode_token, generate_mfa_secret, hash_password, make_access_token,
    make_refresh_token, mfa_provisioning_uri, validate_password_strength,
    verify_mfa, verify_password,
)
from deps import (
    WORKFORCE_ROLES, api, db, get_authenticated_user, to_user_out,
)
from models import (
    LoginIn, MfaVerifyIn, PasswordChange, ProfileUpdate, RefreshIn, TokenOut,
    UserCreate, UserOut, new_id,
)
from sessions import (
    check_and_touch_session, clear_refresh_cookie_kwargs,
    enforce_active_session_limit, hash_refresh_token, issue_first_refresh,
    list_active_sessions_sanitized, refresh_cookie_kwargs,
    revoke_all_user_sessions, revoke_family, rotate_refresh, session_policy_for,
)

# --------------------------------------------------------------------------- #
# Session helpers                                                              #
# --------------------------------------------------------------------------- #
SESSION_TTL = timedelta(days=7)          # matches refresh lifetime
RESET_TOKEN_TTL_MIN = int(os.environ.get("PASSWORD_RESET_TOKEN_TTL_MIN", "30"))


def _hipaa_mode() -> bool:
    return os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}


def _email_hash(email: str) -> str:
    return hashlib.sha256((email or "").lower().strip().encode()).hexdigest()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _create_session(user_doc: dict, request: Request, *, mfa_satisfied: bool) -> tuple[str, str, str]:
    """Insert a new user_sessions row + first opaque refresh token.
    Returns (sid, family_id, raw_refresh_token). The RAW token is meant only
    for the immediate Set-Cookie header — it is never persisted plaintext.
    """
    now = datetime.now(timezone.utc)
    sid = new_id()
    family_id = new_id()
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent") if request else None
    role = user_doc.get("role") or "client"
    idle_min, absolute_lifetime = session_policy_for(role)
    absolute_expires_at = now + absolute_lifetime
    await db.user_sessions.insert_one({
        "id": sid,
        "user_id": user_doc["id"],
        "created_at": now,
        "last_used_at": now,
        # legacy field kept for backwards-compat readers
        "expires_at": absolute_expires_at,
        # Sprint 2: explicit policy fields (frozen at session creation)
        "idle_timeout_minutes": idle_min,
        "absolute_expires_at": absolute_expires_at,
        "revoked_at": None,
        "revoke_reason": None,
        "session_version": int(user_doc.get("session_version") or 1),
        "ip_first": ip,
        "ip_last": ip,
        "user_agent": ua,
        "mfa_satisfied_at": now if mfa_satisfied else None,
        "family_id": family_id,
    })
    raw = await issue_first_refresh(
        user_id=user_doc["id"], session_id=sid, family_id=family_id,
        expires_at=absolute_expires_at, ip=ip, user_agent=ua,
    )
    return sid, family_id, raw


def _set_refresh_cookie(resp: Response, raw: str) -> None:
    resp.set_cookie(value=raw, **refresh_cookie_kwargs())


def _clear_refresh_cookie(resp: Response) -> None:
    resp.set_cookie(value="", **clear_refresh_cookie_kwargs())


async def _revoke_all_sessions(user_id: str, reason: str) -> int:
    r = await revoke_all_user_sessions(user_id, reason)
    return r["sessions_revoked"]


async def _revoke_session(sid: str, reason: str) -> None:
    await db.user_sessions.update_one(
        {"id": sid, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc), "revoke_reason": reason}},
    )
    await db.refresh_tokens.update_many(
        {"session_id": sid, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc), "revoke_reason": reason}},
    )


# --------------------------------------------------------------------------- #
# Registration / Login / Token refresh                                        #
# --------------------------------------------------------------------------- #
@api.post("/auth/register", response_model=TokenOut)
async def register(payload: UserCreate, request: Request):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    reason = validate_password_strength(payload.password, email=payload.email, full_name=payload.full_name or "")
    if reason:
        raise HTTPException(status_code=400, detail=reason)

    role = "client"
    now = datetime.now(timezone.utc)
    user_doc = {
        "id": new_id(),
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "full_name": payload.full_name,
        "phone": payload.phone,
        "role": role,
        "mfa_enabled": False,
        "mfa_secret": None,
        "is_active": True,
        "session_version": 1,
        "password_changed_at": now,
        "created_at": now,
        "last_login_at": None,
    }
    await db.users.insert_one(user_doc)

    await db.clients.insert_one({
        "id": new_id(), "user_id": user_doc["id"],
        "full_name": payload.full_name, "email": payload.email.lower(),
        "phone": payload.phone, "intake_completed": False,
        "created_at": now,
    })

    await log_audit(db, user_doc["id"], user_doc["email"], "auth.register",
                    resource_type="user", resource_id=user_doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    # Clients don't need MFA; workforce sessions start unsatisfied.
    sid, family_id, raw_refresh = await _create_session(user_doc, request, mfa_satisfied=(role not in WORKFORCE_ROLES))
    access = make_access_token(user_doc["id"], role, sid, session_version=user_doc.get("session_version", 1))
    resp = Response()
    _set_refresh_cookie(resp, raw_refresh)
    resp.body = json_dumps_body({"access_token": access, "refresh_token": "", "user": to_user_out(user_doc), "mfa_required": False})
    resp.media_type = "application/json"
    resp.headers["content-length"] = str(len(resp.body))
    return resp


def json_dumps_body(obj) -> bytes:
    import json
    def _default(o):
        if isinstance(o, datetime): return o.isoformat()
        raise TypeError
    return json.dumps(obj, default=_default).encode("utf-8")


@api.post("/auth/login")
async def login(payload: LoginIn, request: Request):
    from rate_limit import enforce_login_rate, is_locked, record_login_failure, reset_login_failures
    # 1) IP + email sliding-window rate limit — protects against distributed brute force.
    enforce_login_rate(request, payload.email)
    # 2) Per-email lockout — brute-force controls independent of the rate window.
    locked, retry_after = is_locked(payload.email)
    if locked:
        raise HTTPException(status_code=423, detail={
            "code": "account_locked",
            "retry_after_seconds": retry_after,
        })

    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        await db.login_history.insert_one({
            "id": new_id(), "user_id": user.get("id") if user else None,
            "email_hash": _email_hash(payload.email),
            "success": False,
            "ip": get_client_ip(request), "user_agent": request.headers.get("user-agent"),
            "ts": datetime.now(timezone.utc),
        })
        record_login_failure(payload.email)
        await log_audit(db, user.get("id") if user else None, payload.email.lower(),
                        "auth.login_fail",
                        severity="warning", outcome="failure",
                        ip=get_client_ip(request),
                        user_agent=request.headers.get("user-agent"))
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    role = user.get("role", "client")
    mfa_satisfied_now = False
    if user.get("mfa_enabled"):
        if not payload.mfa_token:
            return {"access_token": "", "refresh_token": "", "user": to_user_out(user), "mfa_required": True}
        if not verify_mfa(user.get("mfa_secret", ""), payload.mfa_token):
            record_login_failure(payload.email)
            raise HTTPException(status_code=401, detail="Invalid MFA code")
        mfa_satisfied_now = True

    # Success — clear any accumulated failure counter.
    reset_login_failures(payload.email)

    # Active-session limit check BEFORE creating a new session.
    limit_check = await enforce_active_session_limit(user)
    if limit_check["action"] == "reject_workforce":
        # Return a continuation ticket. The user must choose a session to revoke,
        # then call /auth/login/continue with the ticket to actually authenticate.
        ticket_id = new_id()
        await db.login_continuations.insert_one({
            "ticket_id": ticket_id,
            "user_id": user["id"],
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "mfa_satisfied_now": mfa_satisfied_now,
            "consumed_at": None,
        })
        sanitized = await list_active_sessions_sanitized(user["id"])
        raise HTTPException(status_code=409, detail={
            "code": "active_session_limit_exceeded",
            "message": "You have too many active sessions. Sign out of one to continue.",
            "continuation_ticket": ticket_id,
            "expires_in_seconds": 300,
            "active_sessions": sanitized,
            "limit": limit_check["limit"],
        })

    await db.users.update_one({"id": user["id"]}, {"$set": {"last_login_at": datetime.now(timezone.utc)}})
    await db.login_history.insert_one({
        "id": new_id(), "user_id": user["id"], "email_hash": _email_hash(user["email"]),
        "success": True,
        "ip": get_client_ip(request), "user_agent": request.headers.get("user-agent"),
        "ts": datetime.now(timezone.utc),
    })
    await log_audit(db, user["id"], user["email"], "auth.login",
                    resource_type="user", resource_id=user["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    starts_satisfied = mfa_satisfied_now or (role not in WORKFORCE_ROLES)
    sid, family_id, raw_refresh = await _create_session(user, request, mfa_satisfied=starts_satisfied)
    access = make_access_token(user["id"], role, sid, session_version=user.get("session_version", 1))

    body = {"access_token": access, "user": to_user_out(user), "mfa_required": False}
    if limit_check.get("action") == "evicted_oldest":
        body["notice"] = "Another device was signed out to make room for this session."
    resp = Response(content=json_dumps_body(body), media_type="application/json")
    _set_refresh_cookie(resp, raw_refresh)
    return resp


@api.post("/auth/login/continue")
async def login_continue(payload: dict, request: Request):
    """After hitting the workforce active-session cap, the client revokes a
    session (via DELETE /auth/sessions/{id} — but wait, that needs auth; so
    we do it here). Body: {continuation_ticket, revoke_session_id}.
    """
    ticket_id = str(payload.get("continuation_ticket") or "")
    revoke_sid = str(payload.get("revoke_session_id") or "")
    if not ticket_id or not revoke_sid:
        raise HTTPException(status_code=400, detail="Missing ticket or session id")
    row = await db.login_continuations.find_one_and_update(
        {"ticket_id": ticket_id, "consumed_at": None,
         "expires_at": {"$gt": datetime.now(timezone.utc)}},
        {"$set": {"consumed_at": datetime.now(timezone.utc)}},
    )
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired continuation ticket")
    # Revoke the chosen session (must belong to this user).
    target = await db.user_sessions.find_one({"id": revoke_sid, "user_id": row["user_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    await _revoke_session(revoke_sid, "user_chose_revoke")

    user = await db.users.find_one({"id": row["user_id"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    role = user.get("role", "client")

    sid, family_id, raw_refresh = await _create_session(user, request, mfa_satisfied=row.get("mfa_satisfied_now", False))
    access = make_access_token(user["id"], role, sid, session_version=user.get("session_version", 1))
    resp = Response(
        content=json_dumps_body({"access_token": access, "user": to_user_out(user), "mfa_required": False}),
        media_type="application/json",
    )
    _set_refresh_cookie(resp, raw_refresh)
    return resp


@api.post("/auth/refresh")
async def refresh_endpoint(request: Request):
    """Sprint 2: opaque refresh token, atomic rotation with concurrency grace,
    family reuse detection. Reads the token from the `nms_rt` HttpOnly cookie ONLY.
    """
    # Origin allowlist check (CSRF defense).
    allowed = [o.strip() for o in (os.environ.get("ALLOWED_ORIGINS") or "").split(",") if o.strip()]
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if allowed and origin:
        if not any(origin.startswith(a) for a in allowed):
            raise HTTPException(status_code=403, detail="Origin not allowed")

    raw = request.cookies.get("nms_rt") or ""
    if not raw:
        raise HTTPException(status_code=401, detail="Missing refresh cookie")

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    outcome = await rotate_refresh(raw, ip=ip, user_agent=ua)

    if outcome.kind == "unknown":
        resp = Response(content=b'{"detail":"Invalid refresh"}', status_code=401,
                        media_type="application/json")
        _clear_refresh_cookie(resp)
        return resp

    if outcome.kind == "reuse_detected":
        # Family + session already burned by rotate_refresh().
        await log_audit(db, outcome.user_id, None, "auth.refresh_reuse_detected",
                        metadata={"family_id": outcome.family_id, "severity": "high"},
                        ip=ip, user_agent=ua)
        resp = Response(content=b'{"detail":"Invalid refresh"}', status_code=401,
                        media_type="application/json")
        _clear_refresh_cookie(resp)
        return resp

    if outcome.kind == "concurrency_grace":
        # Legitimate concurrent refresh — do NOT burn family, do NOT clear cookie.
        await log_audit(db, outcome.user_id, None, "auth.refresh_concurrency_detected",
                        metadata={"family_id": outcome.family_id, "severity": "info"},
                        ip=ip, user_agent=ua)
        # 409 Conflict signals the client to just retry with the cookie the
        # winning request already installed.
        return Response(content=b'{"detail":"concurrency_retry"}', status_code=409,
                        media_type="application/json")

    # outcome.kind == "rotated"
    user = await db.users.find_one({"id": outcome.user_id})
    if not user or not user.get("is_active", True):
        resp = Response(content=b'{"detail":"User disabled"}', status_code=401,
                        media_type="application/json")
        _clear_refresh_cookie(resp)
        return resp
    access = make_access_token(user["id"], user["role"], outcome.session_id,
                                session_version=user.get("session_version", 1))
    await log_audit(db, user["id"], None, "auth.refresh_rotated",
                    metadata={"family_id": outcome.family_id}, ip=ip, user_agent=ua)
    body = {"access_token": access, "user": to_user_out(user)}
    resp = Response(content=json_dumps_body(body), media_type="application/json")
    _set_refresh_cookie(resp, outcome.raw)
    return resp


@api.post("/auth/logout")
async def logout(request: Request, response: Response, user=Depends(get_authenticated_user)):
    sid = (user.get("_session") or {}).get("id")
    if sid:
        await _revoke_session(sid, "user_logout")
    await log_audit(db, user["id"], user["email"], "auth.logout",
                    resource_type="session", resource_id=sid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    _clear_refresh_cookie(response)
    return {"ok": True}


@api.post("/auth/logout-all")
async def logout_all(request: Request, response: Response, user=Depends(get_authenticated_user)):
    """Revoke every session + refresh family for the authenticated user."""
    r = await revoke_all_user_sessions(user["id"], reason="user_logout_all")
    await log_audit(db, user["id"], user["email"], "auth.sessions_revoked_all",
                    metadata=r, ip=get_client_ip(request),
                    user_agent=request.headers.get("user-agent"))
    _clear_refresh_cookie(response)
    return {"ok": True, **r}


@api.get("/auth/sessions")
async def list_my_sessions(user=Depends(get_authenticated_user)):
    """Return the user's active sessions (sanitized — no raw IPs / full UA)."""
    current_sid = (user.get("_session") or {}).get("id")
    return await list_active_sessions_sanitized(user["id"], current_sid=current_sid)


@api.delete("/auth/sessions/{session_id}")
async def revoke_my_session(session_id: str, request: Request, user=Depends(get_authenticated_user)):
    target = await db.user_sessions.find_one({"id": session_id, "user_id": user["id"]})
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    await _revoke_session(session_id, "user_revoked")
    await log_audit(db, user["id"], user["email"], "auth.session_revoked",
                    resource_type="session", resource_id=session_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.get("/auth/me", response_model=UserOut)
async def me(user=Depends(get_authenticated_user)):
    return to_user_out(user)


# --------------------------------------------------------------------------- #
# Multi-factor authentication                                                 #
# --------------------------------------------------------------------------- #
@api.post("/auth/mfa/setup")
async def mfa_setup(user=Depends(get_authenticated_user)):
    from auth_utils import encrypt_mfa_secret
    secret = generate_mfa_secret()
    uri = mfa_provisioning_uri(secret, user["email"])
    # Store the AES-256-GCM ciphertext — plaintext leaves memory once the response is sent.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"mfa_secret": encrypt_mfa_secret(secret), "mfa_enabled": False}},
    )
    return {"secret": secret, "provisioning_uri": uri}


@api.post("/auth/mfa/verify")
async def mfa_verify(payload: MfaVerifyIn, request: Request, user=Depends(get_authenticated_user)):
    secret = user.get("mfa_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Run /mfa/setup first")
    if not verify_mfa(secret, payload.token):
        raise HTTPException(status_code=401, detail="Invalid code")
    now = datetime.now(timezone.utc)
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_enabled": True}})
    # Mark THIS session as MFA-satisfied so PHI routes stop returning 403 immediately.
    sid = (user.get("_session") or {}).get("id")
    if sid:
        await db.user_sessions.update_one({"id": sid}, {"$set": {"mfa_satisfied_at": now}})
    await log_audit(db, user["id"], user["email"], "auth.mfa_enabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": True}


@api.post("/auth/mfa/disable")
async def mfa_disable(request: Request, user=Depends(get_authenticated_user)):
    """Workforce accounts CANNOT disable MFA (Sprint 1 hard cutover)."""
    if user.get("role") in WORKFORCE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Workforce accounts are not permitted to disable MFA. Contact your security administrator.",
        )
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_enabled": False, "mfa_secret": None}})
    await log_audit(db, user["id"], user["email"], "auth.mfa_disabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": False}


# --------------------------------------------------------------------------- #
# Account profile / password change                                            #
# --------------------------------------------------------------------------- #
@api.put("/auth/me", response_model=UserOut)
async def update_me(payload: ProfileUpdate, request: Request, user=Depends(get_authenticated_user)):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
        await db.clients.update_many(
            {"user_id": user["id"]},
            {"$set": {k: v for k, v in updates.items() if k in ("full_name", "phone")}},
        )
        await log_audit(db, user["id"], user["email"], "account.update",
                        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    u = await db.users.find_one({"id": user["id"]})
    return to_user_out(u)


@api.post("/auth/change-password")
async def change_password(payload: PasswordChange, request: Request, user=Depends(get_authenticated_user)):
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    reason = validate_password_strength(
        payload.new_password, email=user.get("email", ""), full_name=user.get("full_name") or "",
    )
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {"password_hash": hash_password(payload.new_password), "password_changed_at": now},
            "$inc": {"session_version": 1},
        },
    )
    # Revoke every existing session (including current) — user re-logs in with new password.
    await _revoke_all_sessions(user["id"], reason="password_change")
    await log_audit(db, user["id"], user["email"], "account.password_change",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "must_relogin": True}


# --------------------------------------------------------------------------- #
# Password reset — Sprint 1                                                    #
# --------------------------------------------------------------------------- #
_RESET_WINDOW_MIN = 15
_RESET_MAX_PER_EMAIL_WINDOW = 3      # per (email_hash, window)
_RESET_MAX_PER_IP_WINDOW = 10        # per IP, window
_RESET_GLOBAL_ABUSE_THRESHOLD = 200  # per window (blocks system-wide brute force)


async def _reset_rate_limit_ok(email_hash: str, ip: Optional[str]) -> bool:
    since = datetime.now(timezone.utc) - timedelta(minutes=_RESET_WINDOW_MIN)
    global_ct = await db.password_reset_attempts.count_documents({"ts": {"$gte": since}})
    if global_ct >= _RESET_GLOBAL_ABUSE_THRESHOLD:
        return False
    email_ct = await db.password_reset_attempts.count_documents({"email_hash": email_hash, "ts": {"$gte": since}})
    if email_ct >= _RESET_MAX_PER_EMAIL_WINDOW:
        return False
    if ip:
        ip_ct = await db.password_reset_attempts.count_documents({"ip": ip, "ts": {"$gte": since}})
        if ip_ct >= _RESET_MAX_PER_IP_WINDOW:
            return False
    return True


@api.post("/auth/forgot-password")
async def forgot_password(payload: dict, request: Request):
    """Trigger a password-reset email. Response is IDENTICAL for known + unknown emails."""
    from rate_limit import enforce_forgot_rate
    email = str(payload.get("email") or "").strip().lower()
    enforce_forgot_rate(request, email)
    ip = get_client_ip(request)
    email_hash = _email_hash(email) if email else ""
    now = datetime.now(timezone.utc)

    # Record every attempt (used for rate limiting). Never store the raw email.
    await db.password_reset_attempts.insert_one({
        "email_hash": email_hash, "ip": ip, "ts": now,
    })

    # Uniform response regardless of what we do below.
    generic = {"ok": True, "message": "If that email is registered, a reset link is on the way."}

    if not email or not email_hash:
        return generic
    if not await _reset_rate_limit_ok(email_hash, ip):
        # Same response body — attackers can't distinguish rate limit from unknown email.
        return generic

    user = await db.users.find_one({"email": email})
    if not user or not user.get("is_active", True):
        return generic

    # Generate a high-entropy token; store only its SHA-256.
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)
    expires_at = now + timedelta(minutes=RESET_TOKEN_TTL_MIN)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token_hash": token_hash,
        "user_id": user["id"],
        "email_hash": email_hash,
        "created_at": now,
        "expires_at": expires_at,
        "consumed_at": None,
        "ip": ip,
    })

    # Build the reset link — kept in-memory only, never logged.
    frontend_origin = os.environ.get("FRONTEND_ORIGIN") or ""
    reset_url = f"{frontend_origin.rstrip('/')}/reset-password?token={raw_token}" if frontend_origin else f"[configure FRONTEND_ORIGIN]?token={raw_token}"

    from notifiers import send_email as notify_email
    subject = "Reset your NatMedSol password"
    html = (
        "<p>Hi,</p>"
        "<p>Someone (hopefully you) asked to reset the password on your NatMedSol account. "
        f"Follow this link within {RESET_TOKEN_TTL_MIN} minutes to choose a new password:</p>"
        f"<p><a href=\"{reset_url}\">{reset_url}</a></p>"
        "<p>If you didn't request this, you can safely ignore this email.</p>"
        "<p>— NatMedSol Security</p>"
    )
    # redact_recipient=True → integration_log only stores sha256:<prefix>, not the email.
    # No payload_metadata carries the token or URL.
    await notify_email(
        db, email, subject, html,
        action="auth.password_reset_dispatch",
        redact_recipient=True,
    )

    # Redacted audit event — no email, no token, no URL.
    await log_audit(
        db, user["id"], user_email=None, action="auth.password_reset_requested",
        resource_type="user", resource_id=user["id"],
        metadata={"email_hash": email_hash},
        ip=ip, user_agent=request.headers.get("user-agent"),
    )

    return generic


@api.post("/auth/reset-password")
async def reset_password(payload: dict, request: Request):
    raw_token = str(payload.get("token") or "")
    new_pw = str(payload.get("new_password") or "")
    ip = get_client_ip(request)
    if not raw_token or not new_pw:
        raise HTTPException(status_code=400, detail="Missing token or new_password")

    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    # ATOMIC consume: only succeeds if the token is unconsumed AND unexpired
    # (we do NOT rely on the TTL index — TTL cleanup is asynchronous).
    row = await db.password_reset_tokens.find_one_and_update(
        {"token_hash": token_hash, "consumed_at": None, "expires_at": {"$gt": now}},
        {"$set": {"consumed_at": now, "consumed_ip": ip}},
    )
    if not row:
        await log_audit(
            db, user_id=None, user_email=None, action="auth.password_reset_denied",
            metadata={"reason": "invalid_or_expired"}, ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = await db.users.find_one({"id": row["user_id"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=400, detail="Account not eligible for reset")

    reason = validate_password_strength(new_pw, email=user["email"], full_name=user.get("full_name") or "")
    if reason:
        # Roll back the token consumption so the user can try again.
        await db.password_reset_tokens.update_one(
            {"id": row["id"]},
            {"$set": {"consumed_at": None, "consumed_ip": None}},
        )
        raise HTTPException(status_code=400, detail=reason)

    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {"password_hash": hash_password(new_pw), "password_changed_at": now},
            "$inc": {"session_version": 1},
        },
    )
    revoked_ct = await _revoke_all_sessions(user["id"], reason="password_reset")

    await log_audit(
        db, user["id"], user_email=None, action="auth.password_reset_completed",
        resource_type="user", resource_id=user["id"],
        metadata={"revoked_sessions": revoked_ct}, ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return {"ok": True, "must_relogin": True}


# --------------------------------------------------------------------------- #
# DEV-ONLY helper — issue a raw reset token for automated tests directly.     #
# Bypasses the rate limiter so multiple tests can hit it from the same IP.    #
# Explicitly disabled in HIPAA_MODE.                                          #
# --------------------------------------------------------------------------- #
@api.post("/auth/dev/reset-token")
async def dev_reset_token(payload: dict):
    if _hipaa_mode() or os.environ.get("DEV_EXPOSE_RESET_TOKEN", "").lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=404, detail="Not available")
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Missing email")
    user = await db.users.find_one({"email": email})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=404, detail="No such user")
    # Directly issue a fresh reset token — no rate limit, no email dispatch.
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token_hash": _hash_token(raw),
        "user_id": user["id"],
        "email_hash": _email_hash(email),
        "created_at": now,
        "expires_at": now + timedelta(minutes=RESET_TOKEN_TTL_MIN),
        "consumed_at": None,
        "ip": None,
    })
    return {"dev_reset_token": raw, "expires_in_min": RESET_TOKEN_TTL_MIN}


# --------------------------------------------------------------------------- #
# Google SSO — Emergent-managed session exchange                              #
# (Slated to be replaced with direct Google OAuth for BAA compliance.)        #
# --------------------------------------------------------------------------- #
@api.post("/auth/google/session")
async def google_session_exchange(request: Request):
    """Exchange Emergent Auth session_id (header X-Session-ID) for our internal JWT."""
    session_id = request.headers.get("X-Session-ID") or request.headers.get("x-session-id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-ID header")
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": session_id},
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Auth provider unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    data = r.json()
    email = (data.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="No email returned by auth provider")

    user = await db.users.find_one({"email": email})
    if not user:
        # Auto-create new client account
        user = {
            "id": new_id(),
            "email": email,
            "full_name": data.get("name") or email.split("@")[0],
            "role": "client",
            "active": True,
            "auth_provider": "google",
            "picture_url": data.get("picture"),
            "created_at": datetime.now(timezone.utc),
        }
        await db.users.insert_one(user)
        # also create a Clients row so /clients/me works
        await db.clients.insert_one({
            "id": new_id(), "user_id": user["id"],
            "full_name": user["full_name"], "email": email,
            "intake_completed": False,
            "created_at": datetime.now(timezone.utc),
        })
    elif not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    else:
        # Update profile picture / link google
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"auth_provider": "google", "picture_url": data.get("picture")}},
        )

    # Google users are always role=client here → session starts mfa-satisfied.
    sid, family_id, raw_refresh = await _create_session(user, request, mfa_satisfied=(user["role"] not in WORKFORCE_ROLES))
    access = make_access_token(user["id"], user["role"], sid, session_version=user.get("session_version", 1))
    await log_audit(db, user["id"], user["email"], "auth.login_google",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    resp = Response(content=json_dumps_body({
        "access_token": access,
        "user": {"id": user["id"], "email": user["email"], "full_name": user.get("full_name"),
                 "role": user["role"], "picture_url": user.get("picture_url")},
    }), media_type="application/json")
    _set_refresh_cookie(resp, raw_refresh)
    return resp


# --------------------------------------------------------------------------- #
# Direct Google OAuth (replaces Emergent-managed SSO once env vars are set)  #
#                                                                             #
# REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS.   #
# This breaks the auth. All URLs come from env only:                          #
#   GOOGLE_OAUTH_CLIENT_ID                                                    #
#   GOOGLE_OAUTH_CLIENT_SECRET                                                #
#   GOOGLE_OAUTH_REDIRECT_URI  (e.g. https://your.app/api/auth/google/callback)#
#   FRONTEND_ORIGIN            (where to bounce the user after callback)     #
# --------------------------------------------------------------------------- #

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _google_oauth_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        and os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    )


@api.get("/auth/google/oauth/authorize")
async def google_oauth_authorize():
    """Return the Google authorize URL the frontend should redirect the browser to.
    A one-time `state` value is generated and stored briefly in Mongo for CSRF protection."""
    if not _google_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Direct Google OAuth not configured. Set GOOGLE_OAUTH_CLIENT_ID / "
                   "GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REDIRECT_URI in backend/.env.",
        )
    state = secrets.token_urlsafe(32)
    await db.oauth_states.insert_one({
        "state": state,
        "created_at": datetime.now(timezone.utc),
    })
    params = {
        "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        "redirect_uri": os.environ["GOOGLE_OAUTH_REDIRECT_URI"],
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": state,
    }
    return {"authorize_url": f"{_GOOGLE_AUTH_URL}?{urlencode(params)}", "state": state}


@api.get("/auth/google/oauth/callback")
async def google_oauth_callback(request: Request, code: Optional[str] = None,
                                state: Optional[str] = None, error: Optional[str] = None):
    """Handle Google's redirect: exchange code for token, upsert the user, then
    bounce the browser to `${FRONTEND_ORIGIN}/oauth-complete?token=<jwt>&refresh=<jwt>`."""
    if not _google_oauth_configured():
        raise HTTPException(status_code=503, detail="Direct Google OAuth not configured")
    if error:
        raise HTTPException(status_code=400, detail=f"Google returned error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    st = await db.oauth_states.find_one_and_delete({"state": state})
    if not st:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            token_resp = await client.post(_GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
                "redirect_uri": os.environ["GOOGLE_OAUTH_REDIRECT_URI"],
                "grant_type": "authorization_code",
            })
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Google token endpoint unreachable: {e}")

    if token_resp.status_code != 200:
        raise HTTPException(status_code=401, detail=f"Token exchange failed: {token_resp.text}")
    tok = token_resp.json()
    access_google = tok.get("access_token")
    if not access_google:
        raise HTTPException(status_code=401, detail="No access token from Google")

    # Fetch userinfo
    async with httpx.AsyncClient(timeout=15.0) as client:
        ui_resp = await client.get(_GOOGLE_USERINFO_URL,
                                    headers={"Authorization": f"Bearer {access_google}"})
    if ui_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to fetch Google userinfo")
    ui = ui_resp.json()
    email = (ui.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Google returned no email")
    if not ui.get("email_verified", True):
        raise HTTPException(status_code=403, detail="Email not verified with Google")

    # Upsert user + client
    user = await db.users.find_one({"email": email})
    if not user:
        user = {
            "id": new_id(),
            "email": email,
            "full_name": ui.get("name") or email.split("@")[0],
            "role": "client",
            "is_active": True,
            "auth_provider": "google_direct",
            "picture_url": ui.get("picture"),
            "created_at": datetime.now(timezone.utc),
        }
        await db.users.insert_one(user)
        await db.clients.insert_one({
            "id": new_id(), "user_id": user["id"],
            "full_name": user["full_name"], "email": email,
            "intake_completed": False,
            "created_at": datetime.now(timezone.utc),
        })
    elif not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    else:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "auth_provider": "google_direct",
                "picture_url": ui.get("picture"),
                "last_login_at": datetime.now(timezone.utc),
            }},
        )

    sid, family_id, raw_refresh = await _create_session(user, request, mfa_satisfied=(user["role"] not in WORKFORCE_ROLES))
    access = make_access_token(user["id"], user["role"], sid, session_version=user.get("session_version", 1))
    # Store refresh + access under a one-time handoff id so nothing lands in the URL.
    handoff_id = secrets.token_urlsafe(24)
    await db.oauth_handoffs.insert_one({
        "handoff_id": handoff_id,
        "user_id": user["id"],
        "access_token": access,
        "refresh_cookie_value": raw_refresh,
        "created_at": datetime.now(timezone.utc),
        "consumed": False,
    })
    await log_audit(db, user["id"], user["email"], "auth.login_google_direct",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    frontend_origin = os.environ.get("FRONTEND_ORIGIN")
    if not frontend_origin:
        raise HTTPException(status_code=500,
                            detail="FRONTEND_ORIGIN env var required for OAuth completion redirect")
    complete_url = f"{frontend_origin.rstrip('/')}/oauth-complete?handoff={handoff_id}"
    return RedirectResponse(url=complete_url, status_code=302)


@api.post("/auth/google/oauth/exchange")
async def google_oauth_exchange(payload: dict):
    """Redeem a one-time OAuth handoff id (from callback redirect) for the
    access token + user profile. The opaque refresh token is delivered ONLY via
    the `nms_rt` HttpOnly cookie (Sprint 2 policy). Handoff is single-use and
    expires after 5 minutes."""
    handoff_id = (payload or {}).get("handoff_id")
    if not handoff_id:
        raise HTTPException(status_code=400, detail="Missing handoff_id")
    row = await db.oauth_handoffs.find_one_and_update(
        {"handoff_id": handoff_id, "consumed": False},
        {"$set": {"consumed": True, "consumed_at": datetime.now(timezone.utc)}},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Handoff already used or unknown")
    age = (datetime.now(timezone.utc) - row["created_at"].replace(tzinfo=timezone.utc)).total_seconds()
    if age > 300:
        raise HTTPException(status_code=410, detail="Handoff expired (5 min TTL)")
    user = await db.users.find_one({"id": row["user_id"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User inactive")

    resp = Response()
    _set_refresh_cookie(resp, row["refresh_cookie_value"])
    resp.body = json_dumps_body({
        "access_token": row["access_token"],
        "user": {
            "id": user["id"], "email": user["email"], "full_name": user.get("full_name"),
            "role": user.get("role"), "picture_url": user.get("picture_url"),
        },
    })
    resp.media_type = "application/json"
    resp.headers["content-length"] = str(len(resp.body))
    return resp
