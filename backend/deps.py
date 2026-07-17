"""
Shared FastAPI singletons + auth dependencies.

Sprint 1 changes:
- `assert_valid_secret()` runs at import — HIPAA_MODE=on refuses insufficient config.
- `get_authenticated_user()` — decodes access token + verifies session revocation status.
- `require_workforce_mfa()` — 403 with `must_enroll_mfa` when workforce user hasn't finished MFA.
- `require_roles()` composes both: authentication + role + workforce-MFA gate.
- No URL-path allowlist inside `get_authenticated_user` — enrollment routes use it directly (no MFA).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

from audit import get_client_ip, log_audit  # noqa: F401 (re-exported for routers)
from auth_utils import (
    assert_valid_secret, decode_token, get_jwt_audience, get_jwt_issuer,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


# --------------------------------------------------------------------------- #
# Startup configuration assertion                                              #
# --------------------------------------------------------------------------- #
_HIPAA_MODE = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}

# These raise RuntimeError at import if HIPAA_MODE=on and any is missing/weak.
assert_valid_secret()
get_jwt_issuer()
get_jwt_audience()

WORKFORCE_ROLES = {"admin", "practitioner", "staff", "front_desk", "frontdesk", "auditor"}


# --------------------------------------------------------------------------- #
# Mongo                                                                        #
# --------------------------------------------------------------------------- #
_mongo_url = os.environ["MONGO_URL"]
_client = AsyncIOMotorClient(_mongo_url)
db = _client[os.environ["DB_NAME"]]
fs_bucket = AsyncIOMotorGridFSBucket(db, bucket_name="emr_files")


# --------------------------------------------------------------------------- #
# FastAPI plumbing                                                             #
# --------------------------------------------------------------------------- #
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logger = logging.getLogger("nms.emr")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# --------------------------------------------------------------------------- #
# Utility helpers                                                              #
# --------------------------------------------------------------------------- #
def _strip_id(doc):
    if doc is None:
        return None
    d = dict(doc)
    d.pop("_id", None)
    return d


def to_user_out(user) -> dict:
    if user is None:
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user.get("full_name", ""),
        "phone": user.get("phone"),
        "role": user.get("role", "client"),
        "mfa_enabled": user.get("mfa_enabled", False),
        "is_active": user.get("is_active", True),
        "must_change_password": user.get("must_change_password", False),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


async def _resolve_self_client(user) -> Optional[dict]:
    return await db.clients.find_one({"user_id": user["id"]})


def close_mongo():
    _client.close()


# --------------------------------------------------------------------------- #
# Sprint-1 dependency: decode + session-revocation check                       #
# --------------------------------------------------------------------------- #
async def get_authenticated_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
):
    """Verify the bearer JWT + session revocation + session_version + idle/absolute
    timeouts. Only touches `last_used_at` AFTER all checks pass, and throttles
    that write to once per minute (per Sprint 2 gate corrections).
    """
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing auth token")

    payload = decode_token(creds.credentials, expected_type="access")

    sid = payload.get("sid")
    if not sid:
        raise HTTPException(status_code=401, detail="Session binding required; please sign in again.")

    session = await db.user_sessions.find_one({"id": sid})
    if not session:
        raise HTTPException(status_code=401, detail="Session not found")

    # Order of checks per Sprint 2 gate: revoked → absolute → idle → status → session_version → THEN touch.
    from sessions import check_and_touch_session
    reason = await check_and_touch_session(session, get_client_ip(request))
    if reason:
        # Do not silently overwrite — bump the session row's reason field too.
        try:
            await db.user_sessions.update_one(
                {"id": sid, "revoked_at": None},
                {"$set": {"revoked_at": datetime.now(timezone.utc), "revoke_reason": reason}},
            )
        except Exception:
            pass
        raise HTTPException(status_code=401, detail=reason)

    user = await db.users.find_one({"id": payload["sub"]})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    # Session-version staleness: any access token issued before the current version is invalid.
    token_sv = payload.get("sv")
    if token_sv is not None and int(user.get("session_version") or 1) > int(token_sv):
        raise HTTPException(status_code=401, detail="session_version_stale")

    user["_session"] = session
    return user


# Back-compat alias: existing routers import `get_current_user`.
get_current_user = get_authenticated_user


async def require_workforce_mfa(user=Depends(get_authenticated_user)):
    """403 `must_enroll_mfa` when a workforce user hasn't completed MFA setup.
    Client role is exempt (they are not workforce).
    """
    role = user.get("role")
    if role in WORKFORCE_ROLES:
        if not user.get("mfa_enabled"):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "must_enroll_mfa",
                    "message": "Workforce accounts must complete MFA enrollment before accessing PHI.",
                    "next": {"setup": "/api/auth/mfa/setup", "verify": "/api/auth/mfa/verify"},
                },
            )
        # Also require this login's MFA-satisfied timestamp (set only on successful TOTP verify)
        sess = user.get("_session") or {}
        if not sess.get("mfa_satisfied_at"):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "mfa_reauth_required",
                    "message": "MFA verification required for this session.",
                },
            )
    return user


def require_roles(*roles):
    """Role gate. Composes: authentication → workforce-MFA (if applicable) → role check.

    `auditor` retains break-glass READ-only access on any GET (still MFA-gated).
    """
    async def dep(request: Request, user=Depends(require_workforce_mfa)):
        role = user.get("role")
        if role == "auditor" and request.method == "GET":
            try:
                await log_audit(
                    db, user["id"], user["email"], "auditor.break_glass_read",
                    resource_type="endpoint", resource_id=request.url.path,
                    metadata={"emergency": True, "method": request.method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
                )
            except Exception:
                pass
            return user
        if role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dep
