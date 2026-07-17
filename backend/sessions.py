"""
Session lifecycle helpers — Sprint 2.

Central home for:
  * `revoke_all_user_sessions()` — single choke-point used by password change /
    reset, MFA disable/reset, role change, account disable, admin revoke,
    logout-all, and suspected-compromise flows.
  * Opaque refresh-token issue + atomic rotation with concurrency grace.
  * Session touch (idle-timeout aware, throttled to 1 write per minute).

None of this file's helpers ever store or log a raw refresh token — only
`sha256(raw_token)` is persisted.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from audit import log_audit
from deps import db

REFRESH_TTL_DAYS = int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", "7"))
REFRESH_GRACE_SECONDS = int(os.environ.get("REFRESH_CONCURRENCY_GRACE_SECONDS", "5"))
WORKFORCE_IDLE_TIMEOUT_MIN = int(os.environ.get("WORKFORCE_IDLE_TIMEOUT_MIN", "15"))
WORKFORCE_ABSOLUTE_HOURS = int(os.environ.get("WORKFORCE_ABSOLUTE_SESSION_HOURS", "12"))
CLIENT_IDLE_TIMEOUT_MIN = int(os.environ.get("CLIENT_IDLE_TIMEOUT_MIN", "60"))
CLIENT_ABSOLUTE_DAYS = int(os.environ.get("CLIENT_ABSOLUTE_SESSION_DAYS", "7"))
MAX_ACTIVE_WORKFORCE_SESSIONS = int(os.environ.get("MAX_ACTIVE_WORKFORCE_SESSIONS", "5"))
MAX_ACTIVE_CLIENT_SESSIONS = int(os.environ.get("MAX_ACTIVE_CLIENT_SESSIONS", "10"))
TOUCH_THROTTLE_SECONDS = 60  # only re-write last_used_at once per minute
WORKFORCE_ROLES = {"admin", "practitioner", "staff", "front_desk", "frontdesk", "auditor"}


# --------------------------------------------------------------------------- #
# Utility                                                                      #
# --------------------------------------------------------------------------- #
def now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_opaque_refresh_token() -> str:
    """256 bits of entropy encoded as URL-safe base64 (43 chars)."""
    return secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- #
# Session policy resolution                                                    #
# --------------------------------------------------------------------------- #
def session_policy_for(role: str) -> Tuple[int, timedelta]:
    """Return (idle_timeout_minutes, absolute_lifetime) for a given role."""
    if role in WORKFORCE_ROLES:
        return WORKFORCE_IDLE_TIMEOUT_MIN, timedelta(hours=WORKFORCE_ABSOLUTE_HOURS)
    return CLIENT_IDLE_TIMEOUT_MIN, timedelta(days=CLIENT_ABSOLUTE_DAYS)


def max_active_sessions_for(role: str) -> int:
    return MAX_ACTIVE_WORKFORCE_SESSIONS if role in WORKFORCE_ROLES else MAX_ACTIVE_CLIENT_SESSIONS


# --------------------------------------------------------------------------- #
# Central revocation choke-point                                               #
# --------------------------------------------------------------------------- #
async def revoke_all_user_sessions(user_id: str, reason: str,
                                    also_bump_session_version: bool = True) -> dict:
    """Revoke every active session + refresh-token family for a user.

    Called from: password change, password reset, MFA reset/disable, role
    change, account disable, admin revoke, logout-all, suspected compromise.

    Returns counts for auditing.
    """
    ts = now()
    r1 = await db.user_sessions.update_many(
        {"user_id": user_id, "revoked_at": None},
        {"$set": {"revoked_at": ts, "revoke_reason": reason}},
    )
    r2 = await db.refresh_tokens.update_many(
        {"user_id": user_id, "revoked_at": None},
        {"$set": {"revoked_at": ts, "revoke_reason": reason}},
    )
    if also_bump_session_version:
        await db.users.update_one({"id": user_id}, {"$inc": {"session_version": 1}})
    return {"sessions_revoked": r1.modified_count, "tokens_revoked": r2.modified_count}


async def revoke_family(family_id: str, reason: str) -> int:
    """Burn one refresh-token family. Called from reuse-detection path."""
    r = await db.refresh_tokens.update_many(
        {"family_id": family_id, "revoked_at": None},
        {"$set": {"revoked_at": now(), "revoke_reason": reason}},
    )
    return r.modified_count


# --------------------------------------------------------------------------- #
# Session creation with active-limit enforcement                               #
# --------------------------------------------------------------------------- #
async def enforce_active_session_limit(user: dict) -> dict:
    """Called during login. Returns a dict describing what happened.

    Client roles: revoke the oldest session automatically ('evict-oldest').
    Workforce roles: refuse to create the session (raise `SessionLimitExceeded`).
    """
    role = user.get("role") or "client"
    limit = max_active_sessions_for(role)
    active_count = await db.user_sessions.count_documents({
        "user_id": user["id"], "revoked_at": None,
        "absolute_expires_at": {"$gt": now()},
    })
    if active_count < limit:
        return {"action": "none", "active_count": active_count, "limit": limit}

    if role in WORKFORCE_ROLES:
        return {"action": "reject_workforce", "active_count": active_count, "limit": limit}

    # Client: silently evict the OLDEST session
    oldest = await db.user_sessions.find_one(
        {"user_id": user["id"], "revoked_at": None},
        sort=[("created_at", 1)],
    )
    if oldest:
        await db.user_sessions.update_one(
            {"id": oldest["id"]},
            {"$set": {"revoked_at": now(), "revoke_reason": "client_evicted_oldest"}},
        )
        await db.refresh_tokens.update_many(
            {"session_id": oldest["id"], "revoked_at": None},
            {"$set": {"revoked_at": now(), "revoke_reason": "session_evicted"}},
        )
    return {"action": "evicted_oldest", "evicted_session_id": (oldest or {}).get("id")}


async def list_active_sessions_sanitized(user_id: str, current_sid: Optional[str] = None) -> list:
    """Return the sanitized session list for the login-continuation flow.
    Workforce users must never see raw IPs or full user-agents.
    """
    sessions = await db.user_sessions.find({
        "user_id": user_id, "revoked_at": None,
    }).sort("last_used_at", -1).to_list(20)
    out = []
    for s in sessions:
        ua = s.get("user_agent") or ""
        label = "Unknown device"
        low = ua.lower()
        if "iphone" in low or "ipad" in low: label = "iPhone / iPad"
        elif "android" in low:               label = "Android device"
        elif "macintosh" in low:             label = "Mac"
        elif "windows" in low:               label = "Windows"
        elif "linux" in low:                 label = "Linux"
        if "chrome" in low: label += " · Chrome"
        elif "firefox" in low: label += " · Firefox"
        elif "safari" in low: label += " · Safari"
        last = _as_utc(s.get("last_used_at")) or _as_utc(s.get("created_at"))
        out.append({
            "session_id": s["id"],
            "device_label": label,
            "last_active_at": last.isoformat() if last else None,
            "created_at": _as_utc(s["created_at"]).isoformat(),
            "is_current": s["id"] == current_sid,
        })
    return out


# --------------------------------------------------------------------------- #
# Refresh-token family — issue + atomic rotate with concurrency grace          #
# --------------------------------------------------------------------------- #
async def issue_first_refresh(user_id: str, session_id: str,
                              family_id: str,
                              expires_at: datetime,
                              ip: Optional[str],
                              user_agent: Optional[str]) -> str:
    """Called once at login. Returns the RAW refresh token (returned in Set-Cookie)."""
    raw = generate_opaque_refresh_token()
    await db.refresh_tokens.insert_one({
        "id": secrets.token_hex(16),
        "token_hash": hash_refresh_token(raw),
        "session_id": session_id,
        "user_id": user_id,
        "family_id": family_id,
        "generation": 0,
        "parent_token_id": None,
        "created_at": now(),
        "last_used_at": None,
        "expires_at": expires_at,
        "used_at": None,
        "replaced_by_id": None,
        "revoked_at": None,
        "revoke_reason": None,
        "ip_created": ip,
        "ip_last_used": None,
        "user_agent_created": user_agent,
    })
    return raw


class RefreshOutcome:
    def __init__(self, kind: str, **extra):
        self.kind = kind        # 'rotated' | 'concurrency_grace' | 'reuse_detected' | 'unknown'
        self.__dict__.update(extra)


async def rotate_refresh(raw_token: str, ip: Optional[str],
                         user_agent: Optional[str]) -> RefreshOutcome:
    """Atomically consume the presented refresh token and mint a successor.

    Concurrency grace: if the presented token was used within the last
    `REFRESH_CONCURRENCY_GRACE_SECONDS` from a similar device context, treat
    it as a legitimate concurrent request and return the LATEST successor's
    raw token (idempotency). The client should just retry with the cookie
    that the winning request already set.

    Confirmed reuse (outside grace, or with materially different device
    context) burns the entire family + associated session.
    """
    ts = now()
    token_hash = hash_refresh_token(raw_token)

    # Step 1: try to atomically claim the token if it's still fresh.
    row = await db.refresh_tokens.find_one_and_update(
        {"token_hash": token_hash, "used_at": None, "revoked_at": None,
         "expires_at": {"$gt": ts}},
        {"$set": {"used_at": ts, "last_used_at": ts, "ip_last_used": ip}},
    )

    if row is not None:
        # We won the race — mint the successor.
        session = await db.user_sessions.find_one({"id": row["session_id"]})
        if not session or session.get("revoked_at") is not None:
            await revoke_family(row["family_id"], "session_gone")
            return RefreshOutcome("unknown")

        # Successor expires at the earliest of (now+TTL, session absolute expiry).
        abs_exp = _as_utc(session["absolute_expires_at"])
        soft_exp = ts + timedelta(days=REFRESH_TTL_DAYS)
        expires_at = min(soft_exp, abs_exp)

        successor_raw = generate_opaque_refresh_token()
        successor_id = secrets.token_hex(16)
        await db.refresh_tokens.insert_one({
            "id": successor_id,
            "token_hash": hash_refresh_token(successor_raw),
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "family_id": row["family_id"],
            "generation": row["generation"] + 1,
            "parent_token_id": row["id"],
            "created_at": ts,
            "last_used_at": None,
            "expires_at": expires_at,
            "used_at": None,
            "replaced_by_id": None,
            "revoked_at": None,
            "revoke_reason": None,
            "ip_created": ip,
            "ip_last_used": None,
            "user_agent_created": user_agent,
        })
        await db.refresh_tokens.update_one(
            {"id": row["id"]},
            {"$set": {"replaced_by_id": successor_id}},
        )
        return RefreshOutcome(
            "rotated", raw=successor_raw,
            session_id=row["session_id"], user_id=row["user_id"],
            family_id=row["family_id"], expires_at=expires_at,
        )

    # Step 2: token was NOT claimable. Check if it exists in a used/revoked state.
    prior = await db.refresh_tokens.find_one({"token_hash": token_hash})
    if not prior:
        return RefreshOutcome("unknown")

    if prior.get("revoked_at") is not None:
        # Already-revoked reuse → treat as confirmed reuse (attacker with old token).
        await revoke_family(prior["family_id"], "reuse_after_revoke")
        await db.user_sessions.update_one(
            {"id": prior["session_id"]},
            {"$set": {"revoked_at": ts, "revoke_reason": "refresh_reuse_detected"}},
        )
        return RefreshOutcome("reuse_detected", family_id=prior["family_id"],
                              session_id=prior["session_id"], user_id=prior["user_id"])

    # Token was used — decide grace vs. reuse.
    used_at = _as_utc(prior["used_at"])
    within_grace = (ts - used_at).total_seconds() <= REFRESH_GRACE_SECONDS
    same_ua = (prior.get("user_agent_created") or "") == (user_agent or "")

    if within_grace and same_ua:
        # Legitimate concurrent refresh. Return the successor that the winning
        # caller already installed — client will just reuse the newer cookie.
        successor = await db.refresh_tokens.find_one({"id": prior.get("replaced_by_id")})
        return RefreshOutcome("concurrency_grace",
                              family_id=prior["family_id"],
                              session_id=prior["session_id"],
                              user_id=prior["user_id"],
                              successor_present=bool(successor))

    # Outside grace OR different device context → confirmed reuse.
    await revoke_family(prior["family_id"], "reuse_detected")
    await db.user_sessions.update_one(
        {"id": prior["session_id"]},
        {"$set": {"revoked_at": ts, "revoke_reason": "refresh_reuse_detected"}},
    )
    return RefreshOutcome("reuse_detected", family_id=prior["family_id"],
                          session_id=prior["session_id"], user_id=prior["user_id"])


# --------------------------------------------------------------------------- #
# Session touch — evaluate idle BEFORE writing, throttle writes                #
# --------------------------------------------------------------------------- #
async def check_and_touch_session(session: dict, ip: Optional[str]) -> Optional[str]:
    """Return None if session is valid; otherwise a rejection reason string.

    Order of checks (per gate correction):
      1. revoked_at
      2. absolute_expires_at
      3. idle timeout against EXISTING last_used_at (pre-touch)
      4. session_version staleness (caller checks against user doc separately)
      5. THEN touch last_used_at — throttled to once per TOUCH_THROTTLE_SECONDS.
    """
    ts = now()
    if session.get("revoked_at") is not None:
        return "session_revoked"

    abs_exp = _as_utc(session.get("absolute_expires_at"))
    if abs_exp and abs_exp < ts:
        return "session_absolute_expired"

    idle_min = int(session.get("idle_timeout_minutes") or WORKFORCE_IDLE_TIMEOUT_MIN)
    last_used = _as_utc(session.get("last_used_at") or session.get("created_at"))
    if last_used and (ts - last_used) > timedelta(minutes=idle_min):
        return "session_idle_expired"

    # Throttled touch — only write if the stored value is stale.
    if not last_used or (ts - last_used).total_seconds() > TOUCH_THROTTLE_SECONDS:
        try:
            await db.user_sessions.update_one(
                {"id": session["id"]},
                {"$set": {"last_used_at": ts, "ip_last": ip}},
            )
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# Cookie settings                                                              #
# --------------------------------------------------------------------------- #
def refresh_cookie_kwargs() -> dict:
    """FastAPI Response.set_cookie() kwargs. Path scoped to /api/auth/refresh."""
    hipaa = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}
    return {
        "key": "nms_rt",
        "httponly": True,
        "secure": hipaa,                     # dev: false so localhost testing works
        "samesite": "lax",
        "path": "/api/auth/refresh",
        "max_age": REFRESH_TTL_DAYS * 86400,
    }


def clear_refresh_cookie_kwargs() -> dict:
    kw = refresh_cookie_kwargs()
    kw.update({"max_age": 0, "expires": 0})
    return kw
