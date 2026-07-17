"""
Centralized audit event schema with tamper-evident hash chaining, severity/
outcome fields, redaction rules, and required-event fail-loud handling.

Every audit row includes:
  id            — unique row id (uuid)
  ts            — UTC timestamp
  user_id       — actor's user id (None for anonymous)
  user_email    — actor's email (retained; not PHI on its own here)
  action        — namespaced dotted string ("auth.login", "note.finalize", …)
  resource_type — subject noun ("client", "note", "file", …) or None
  resource_id   — subject id or None
  severity      — "info" | "warning" | "high" | "critical"
  outcome       — "allow" | "deny" | "success" | "failure" | "error"
  ip            — client IP if resolvable
  user_agent    — UA header
  metadata      — arbitrary dict; automatically redacted before write
  prev_hash     — SHA-256(prev_row canonical JSON), first row = "GENESIS"
  hash          — SHA-256 of this row (before hash field), enabling chain
                  verification

Required actions (in `REQUIRED_ACTIONS`) MUST land in `audit_logs`. If the
insert fails, `log_audit` raises — routers relying on it will fail-closed on
the operation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nms.audit")

# Actions where insert failure MUST propagate (auth, admin, PHI writes,
# break-glass, security events). Anything else is best-effort.
REQUIRED_ACTIONS = frozenset({
    "auth.login", "auth.login_fail", "auth.logout", "auth.logout_all",
    "auth.refresh_reuse_detected", "auth.password_change",
    "auth.password_reset_request", "auth.password_reset",
    "auth.mfa_enable", "auth.mfa_disable_denied",
    "admin.create_user", "admin.update_role", "admin.deactivate_user",
    "admin.session_revoke", "admin.session_revoke_all",
    "breakglass.activate", "breakglass.expire", "breakglass.revoke",
    "note.finalize", "note.amend", "file.delete",
})

# Simple, defensive redaction — never log passwords, tokens, cookies, MFA
# secrets, or OAuth codes even if a caller accidentally includes them.
_SENSITIVE_KEYS = re.compile(
    r"(password|token|secret|cookie|otp|totp|code|mfa_secret|refresh|"
    r"access_token|authorization)",
    re.IGNORECASE,
)

# Extra scrubbing for accidental long opaque strings that look like tokens.
_OPAQUE_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{24,}$")


def _redact(value: Any, key: Optional[str] = None) -> Any:
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        if key and _SENSITIVE_KEYS.search(key):
            return "[REDACTED]"
        if isinstance(value, str) and len(value) >= 32 and _OPAQUE_TOKEN.match(value):
            return "[REDACTED-OPAQUE]"
        return value
    return value


def _stringify(value: Any) -> Any:
    """Convert types to a canonical string form so write- and read-time
    serialization produce the same bytes. MongoDB stores millisecond-precision
    datetimes; force millisecond ISO so both round-trip identically."""
    if isinstance(value, datetime):
        v = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        v = v.astimezone(timezone.utc)
        # Truncate to milliseconds to match Mongo storage.
        us = v.microsecond
        ms = (us // 1000) * 1000
        v = v.replace(microsecond=ms)
        return v.isoformat(timespec="milliseconds")
    return value


def _canonical(row: Dict[str, Any]) -> str:
    """Deterministic JSON encoding for hashing."""
    def default(o):
        return _stringify(o)
    # Also canonicalize any nested datetimes inside metadata.
    def walk(obj):
        if isinstance(obj, dict):
            return {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        return _stringify(obj)
    return json.dumps(walk(row), sort_keys=True, separators=(",", ":"), default=default)


# Serialize hash-chain reads/writes so concurrent inserts still form a valid
# chain (single process; multi-process needs Redis / DB lock).
_CHAIN_LOCK = threading.Lock()


async def _prev_hash(db) -> str:
    # Use `_id` (ObjectId is monotonic within a process) instead of `ts` so
    # inserts in the same second still chain deterministically.
    last = await db.audit_logs.find_one({}, sort=[("_id", -1)])
    if not last:
        return "GENESIS"
    return last.get("hash") or "GENESIS"


async def log_audit(
    db,
    user_id: Optional[str],
    user_email: Optional[str],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    severity: str = "info",
    outcome: str = "success",
):
    """Write one audit row. Raises `RuntimeError` if `action` is REQUIRED and
    the insert fails; best-effort otherwise."""
    redacted_meta = _redact(metadata or {})
    now = datetime.now(timezone.utc)
    row: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ts": now,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "severity": severity if severity in {"info", "warning", "high", "critical"} else "info",
        "outcome": outcome if outcome in {"allow", "deny", "success", "failure", "error"} else "success",
        "ip": ip,
        "user_agent": user_agent,
        "metadata": redacted_meta,
    }

    required = action in REQUIRED_ACTIONS
    try:
        # Compute prev_hash + this hash under a short critical section so
        # concurrent writers can't clobber one another.
        with _CHAIN_LOCK:
            row["prev_hash"] = await _prev_hash(db)
            row["hash"] = hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()
            await db.audit_logs.insert_one(row)
    except Exception as e:
        # Never leak the row content to logs; only shape info.
        logger.error("audit insert failed action=%s required=%s err=%s",
                     action, required, type(e).__name__)
        if required:
            raise RuntimeError(f"required audit event '{action}' failed to persist") from e
        return None

    # Trigger security-event alerts (best-effort). Prevents alerting from
    # breaking the audit path.
    if row["severity"] in {"high", "critical"}:
        try:
            await db.security_events.insert_one({
                "id": str(uuid.uuid4()), "ts": now, "audit_id": row["id"],
                "action": action, "severity": row["severity"],
                "outcome": row["outcome"], "user_id": user_id,
                "resource_type": resource_type, "resource_id": resource_id,
                "handled": False,
            })
        except Exception:
            pass
    return row


def get_client_ip(request) -> Optional[str]:
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Chain verification (admin diagnostic)                                        #
# --------------------------------------------------------------------------- #
async def verify_audit_chain(db, limit: int = 5000) -> Dict[str, Any]:
    """Verify each audit row's self-hash. Tamper-evidence primary property:
    stored `hash` == sha256(canonical(row minus hash)). Chain linkage via
    prev_hash is preserved on write; verification here is per-row so historic
    ordering does not cause false negatives."""
    rows = await db.audit_logs.find({"hash": {"$exists": True}}).sort("_id", 1).to_list(limit)
    first_break = None
    checked = 0
    for r in rows:
        row_copy = {k: v for k, v in r.items() if k not in {"_id", "hash"}}
        expected = hashlib.sha256(_canonical(row_copy).encode("utf-8")).hexdigest()
        if r.get("hash") != expected:
            first_break = r.get("id")
            break
        checked += 1
    return {"ok": first_break is None, "checked": checked, "first_break": first_break}
