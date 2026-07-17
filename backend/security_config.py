"""
Startup configuration validator.

Called from `server.py` on startup. In HIPAA mode we hard-fail on unsafe
settings so the process refuses to serve traffic rather than silently ship
with reduced controls.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("nms.config")


def _truthy(v) -> bool:
    return (v or "").lower() in {"1", "true", "yes", "on"}


class UnsafeProductionConfig(RuntimeError):
    """Raised when HIPAA_MODE is enabled but the runtime configuration is
    incompatible with a HIPAA-aligned deployment."""


def enforce_production_config():
    """Validate the process env against the production security bar. Refuses
    to start when HIPAA_MODE=true is combined with unsafe values."""
    hipaa = _truthy(os.environ.get("HIPAA_MODE"))
    problems: list[str] = []

    # -- Rate limiting must NOT be disabled in prod ---------------------- #
    if hipaa and _truthy(os.environ.get("RATE_LIMIT_TEST_MODE")):
        problems.append(
            "RATE_LIMIT_TEST_MODE=1 is set alongside HIPAA_MODE=true; "
            "brute-force protection is disabled. Unset RATE_LIMIT_TEST_MODE "
            "before starting the process."
        )

    # -- Dev reset-token helper must be off ------------------------------ #
    if hipaa and _truthy(os.environ.get("DEV_EXPOSE_RESET_TOKEN")):
        problems.append(
            "DEV_EXPOSE_RESET_TOKEN=1 is set alongside HIPAA_MODE=true; "
            "password-reset tokens must never be returned to the client."
        )

    # -- Malware scanner must not be a stub ------------------------------ #
    scan_mode = (os.environ.get("MALWARE_SCAN_MODE") or "").lower()
    if hipaa and scan_mode in {"", "stub_clean", "stub_infected"}:
        problems.append(
            f"MALWARE_SCAN_MODE={scan_mode or '<unset>'} is a stub; "
            "HIPAA_MODE requires 'clamd' or 'clamscan'."
        )

    # -- Refresh cookie must be SameSite/Secure -------------------------- #
    refresh_secure = (os.environ.get("REFRESH_COOKIE_SECURE") or "true").lower()
    if hipaa and refresh_secure not in {"1", "true", "yes", "on"}:
        problems.append(
            "REFRESH_COOKIE_SECURE must be true under HIPAA_MODE (cookies must "
            "be delivered over TLS only)."
        )

    # -- Session secret must be a real value ----------------------------- #
    jwt_secret = os.environ.get("SESSION_JWT_SECRET") or ""
    if hipaa and (len(jwt_secret) < 32 or jwt_secret.startswith("dev-")):
        problems.append(
            "SESSION_JWT_SECRET must be at least 32 chars and not a dev-* "
            "placeholder in HIPAA_MODE."
        )

    # -- MFA encryption key must be present ------------------------------ #
    if hipaa and not (os.environ.get("MFA_ENC_KEY_B64") or "").strip():
        problems.append("MFA_ENC_KEY_B64 must be set in HIPAA_MODE.")

    # -- Warn (non-fatal) on stub email/SMS in HIPAA mode ---------------- #
    if hipaa and not (os.environ.get("SENDGRID_API_KEY") or "").strip():
        logger.warning("HIPAA_MODE: SendGrid not configured — email notifications will fall back to sent_stub")
    if hipaa and not (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip():
        logger.warning("HIPAA_MODE: Twilio not configured — SMS notifications will fall back to sent_stub")

    if problems:
        for p in problems:
            logger.error("UNSAFE PRODUCTION CONFIG: %s", p)
        raise UnsafeProductionConfig(
            "HIPAA_MODE production configuration validation failed: "
            + "; ".join(problems)
        )
    logger.info("Production config OK (hipaa=%s, scan_mode=%s)",
                hipaa, scan_mode or "stub_clean")
