"""
Authentication + Account routes.

Extracted from server.py during Phase 16 refactor.
All routes still register on the shared `deps.api` APIRouter (`/api` prefix).
"""
from datetime import datetime, timezone
from typing import Optional
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from audit import get_client_ip, log_audit
from auth_utils import (
    decode_token, generate_mfa_secret, hash_password, make_access_token,
    make_refresh_token, mfa_provisioning_uri, validate_password_strength,
    verify_mfa, verify_password,
)
from deps import api, db, get_current_user, to_user_out
from models import (
    LoginIn, MfaVerifyIn, PasswordChange, ProfileUpdate, RefreshIn, TokenOut,
    UserCreate, UserOut, new_id,
)


# --------------------------------------------------------------------------- #
# Registration / Login / Token refresh                                        #
# --------------------------------------------------------------------------- #
@api.post("/auth/register", response_model=TokenOut)
async def register(payload: UserCreate, request: Request):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    # NIST-modern password validation
    reason = validate_password_strength(payload.password, email=payload.email, full_name=payload.full_name or "")
    if reason:
        raise HTTPException(status_code=400, detail=reason)

    role = "client"
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
        "created_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }
    await db.users.insert_one(user_doc)

    client_doc = {
        "id": new_id(),
        "user_id": user_doc["id"],
        "full_name": payload.full_name,
        "email": payload.email.lower(),
        "phone": payload.phone,
        "intake_completed": False,
        "created_at": datetime.now(timezone.utc),
    }
    await db.clients.insert_one(client_doc)

    await log_audit(db, user_doc["id"], user_doc["email"], "auth.register",
                    resource_type="user", resource_id=user_doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    access = make_access_token(user_doc["id"], role)
    refresh = make_refresh_token(user_doc["id"])
    return {"access_token": access, "refresh_token": refresh, "user": to_user_out(user_doc), "mfa_required": False}


@api.post("/auth/login", response_model=TokenOut)
async def login(payload: LoginIn, request: Request):
    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        await db.login_history.insert_one({
            "id": new_id(), "user_id": user.get("id") if user else None,
            "email": payload.email.lower(), "success": False,
            "ip": get_client_ip(request), "user_agent": request.headers.get("user-agent"),
            "ts": datetime.now(timezone.utc),
        })
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    if user.get("mfa_enabled"):
        if not payload.mfa_token:
            return {"access_token": "", "refresh_token": "", "user": to_user_out(user), "mfa_required": True}
        if not verify_mfa(user.get("mfa_secret", ""), payload.mfa_token):
            raise HTTPException(status_code=401, detail="Invalid MFA code")

    await db.users.update_one({"id": user["id"]}, {"$set": {"last_login_at": datetime.now(timezone.utc)}})
    await db.login_history.insert_one({
        "id": new_id(), "user_id": user["id"], "email": user["email"], "success": True,
        "ip": get_client_ip(request), "user_agent": request.headers.get("user-agent"),
        "ts": datetime.now(timezone.utc),
    })
    await log_audit(db, user["id"], user["email"], "auth.login",
                    resource_type="user", resource_id=user["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    access = make_access_token(user["id"], user["role"])
    refresh = make_refresh_token(user["id"])
    return {"access_token": access, "refresh_token": refresh, "user": to_user_out(user), "mfa_required": False}


@api.post("/auth/refresh", response_model=TokenOut)
async def refresh_token(payload: RefreshIn):
    data = decode_token(payload.refresh_token)
    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    user = await db.users.find_one({"id": data["sub"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=401, detail="User not found or disabled")
    access = make_access_token(user["id"], user["role"])
    refresh = make_refresh_token(user["id"])
    return {"access_token": access, "refresh_token": refresh, "user": to_user_out(user), "mfa_required": False}


@api.post("/auth/logout")
async def logout(request: Request, user=Depends(get_current_user)):
    await log_audit(db, user["id"], user["email"], "auth.logout",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.get("/auth/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return to_user_out(user)


# --------------------------------------------------------------------------- #
# Multi-factor authentication                                                 #
# --------------------------------------------------------------------------- #
@api.post("/auth/mfa/setup")
async def mfa_setup(user=Depends(get_current_user)):
    secret = generate_mfa_secret()
    uri = mfa_provisioning_uri(secret, user["email"])
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_secret": secret, "mfa_enabled": False}})
    return {"secret": secret, "provisioning_uri": uri}


@api.post("/auth/mfa/verify")
async def mfa_verify(payload: MfaVerifyIn, request: Request, user=Depends(get_current_user)):
    secret = user.get("mfa_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Run /mfa/setup first")
    if not verify_mfa(secret, payload.token):
        raise HTTPException(status_code=401, detail="Invalid code")
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_enabled": True}})
    await log_audit(db, user["id"], user["email"], "auth.mfa_enabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": True}


@api.post("/auth/mfa/disable")
async def mfa_disable(request: Request, user=Depends(get_current_user)):
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_enabled": False, "mfa_secret": None}})
    await log_audit(db, user["id"], user["email"], "auth.mfa_disabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": False}


# --------------------------------------------------------------------------- #
# Account profile / password change                                            #
# --------------------------------------------------------------------------- #
@api.put("/auth/me", response_model=UserOut)
async def update_me(payload: ProfileUpdate, request: Request, user=Depends(get_current_user)):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
        # also keep client doc in sync if exists
        await db.clients.update_many(
            {"user_id": user["id"]},
            {"$set": {k: v for k, v in updates.items() if k in ("full_name", "phone")}},
        )
        await log_audit(db, user["id"], user["email"], "account.update",
                        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    u = await db.users.find_one({"id": user["id"]})
    return to_user_out(u)


@api.post("/auth/change-password")
async def change_password(payload: PasswordChange, request: Request, user=Depends(get_current_user)):
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    reason = validate_password_strength(
        payload.new_password, email=user.get("email", ""), full_name=user.get("full_name") or "",
    )
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": hash_password(payload.new_password),
            "password_changed_at": datetime.now(timezone.utc),
        }},
    )
    await log_audit(db, user["id"], user["email"], "account.password_change",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


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

    access = make_access_token(user["id"], user["role"])
    refresh = make_refresh_token(user["id"])
    await log_audit(db, user["id"], user["email"], "auth.login_google",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user.get("full_name"),
            "role": user["role"],
            "picture_url": user.get("picture_url"),
        },
    }


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

    access = make_access_token(user["id"], user["role"])
    refresh = make_refresh_token(user["id"])
    await log_audit(db, user["id"], user["email"], "auth.login_google_direct",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    frontend_origin = os.environ.get("FRONTEND_ORIGIN")
    if not frontend_origin:
        # Deliberately no fallback — the redirect target must come from env only.
        raise HTTPException(status_code=500,
                            detail="FRONTEND_ORIGIN env var required for OAuth completion redirect")
    # Store tokens under a one-time handoff id (5-minute TTL) so we never expose them
    # in the browser URL, history, or referer headers.
    handoff_id = secrets.token_urlsafe(24)
    await db.oauth_handoffs.insert_one({
        "handoff_id": handoff_id,
        "user_id": user["id"],
        "access_token": access,
        "refresh_token": refresh,
        "created_at": datetime.now(timezone.utc),
        "consumed": False,
    })
    complete_url = f"{frontend_origin.rstrip('/')}/oauth-complete?handoff={handoff_id}"
    return RedirectResponse(url=complete_url, status_code=302)


@api.post("/auth/google/oauth/exchange")
async def google_oauth_exchange(payload: dict):
    """Redeem a one-time OAuth handoff id (from callback redirect) for access+refresh tokens.
    Handoff is single-use and expires after 5 minutes."""
    handoff_id = (payload or {}).get("handoff_id")
    if not handoff_id:
        raise HTTPException(status_code=400, detail="Missing handoff_id")
    row = await db.oauth_handoffs.find_one_and_update(
        {"handoff_id": handoff_id, "consumed": False},
        {"$set": {"consumed": True, "consumed_at": datetime.now(timezone.utc)}},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Handoff already used or unknown")
    age = (datetime.now(timezone.utc) - row["created_at"]).total_seconds()
    if age > 300:
        raise HTTPException(status_code=410, detail="Handoff expired (5 min TTL)")
    user = await db.users.find_one({"id": row["user_id"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User inactive")
    return {
        "access_token": row["access_token"],
        "refresh_token": row["refresh_token"],
        "user": {
            "id": user["id"], "email": user["email"], "full_name": user.get("full_name"),
            "role": user.get("role"), "picture_url": user.get("picture_url"),
        },
    }
