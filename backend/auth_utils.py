"""
Cryptographic + auth helpers.

Sprint 1 changes:
- JWTs now include `iss`, `aud`, `jti`, and `sid` (session id) claims.
- `decode_token()` enforces `iss`, `aud`, and token type in addition to signature + expiry.
- `assert_valid_secret()` validates JWT_SECRET entropy (Shannon > 3.5 bits/char AND ≥ 32 chars).
- No default `JWT_SECRET` in HIPAA mode — startup fails hard if unset (see deps.py).
"""
import math
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
import pyotp
from fastapi import HTTPException

JWT_ALGO = "HS256"
ACCESS_TTL_MIN = 15
REFRESH_TTL_DAYS = 7


# --------------------------------------------------------------------------- #
# Configuration surface — deps.py runs assert_config_ok() at startup.         #
# --------------------------------------------------------------------------- #
def _hipaa_mode() -> bool:
    return os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


_DEV_ONLY_SECRETS = {
    "dev-secret-change-me-in-prod-please",
    "change-me-in-production-use-a-long-random-string-here-please-123",
    "changeme", "secret", "jwt-secret",
}


def assert_valid_secret() -> str:
    """Return the effective JWT_SECRET or raise a startup error.
    In HIPAA mode: refuse any dev/weak/missing value.
    In non-HIPAA mode: allow a documented dev fallback ONLY when HIPAA_MODE is off.
    """
    secret = os.environ.get("JWT_SECRET", "")
    if _hipaa_mode():
        if not secret:
            raise RuntimeError("HIPAA_MODE=on: JWT_SECRET is required (min 32 chars, Shannon entropy > 3.5).")
        if secret.lower() in _DEV_ONLY_SECRETS:
            raise RuntimeError("HIPAA_MODE=on: JWT_SECRET must not be a documented dev fallback.")
        if len(secret) < 32:
            raise RuntimeError(f"HIPAA_MODE=on: JWT_SECRET must be ≥32 chars (got {len(secret)}).")
        if _shannon_entropy(secret) < 3.5:
            raise RuntimeError("HIPAA_MODE=on: JWT_SECRET has insufficient entropy (Shannon < 3.5).")
        return secret
    # non-HIPAA (dev/preview) — allow the documented dev secret so hot-reload doesn't kill tests
    return secret or "dev-secret-change-me-in-prod-please"


def get_jwt_issuer() -> str:
    v = os.environ.get("JWT_ISSUER")
    if _hipaa_mode() and not v:
        raise RuntimeError("HIPAA_MODE=on: JWT_ISSUER is required.")
    return v or "natmedsol-emr-dev"


def get_jwt_audience() -> str:
    v = os.environ.get("JWT_AUDIENCE")
    if _hipaa_mode() and not v:
        raise RuntimeError("HIPAA_MODE=on: JWT_AUDIENCE is required.")
    return v or "natmedsol-app-dev"


# --------------------------------------------------------------------------- #
# Passwords                                                                    #
# --------------------------------------------------------------------------- #
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


COMMON_PASSWORDS = {
    "password", "password1", "password123", "password1234",
    "12345678", "123456789", "1234567890", "qwerty", "qwertyuiop",
    "letmein", "welcome", "welcome1", "iloveyou", "admin", "administrator",
    "changeme", "changeme1", "monkey", "dragon", "abc123", "test1234",
    "passw0rd", "p@ssw0rd", "master", "shadow", "sunshine", "princess",
    "football", "baseball", "starwars", "natmedsol", "wellness", "ravello",
}


def validate_password_strength(pw: str, email: str = "", full_name: str = "") -> Optional[str]:
    if not pw or len(pw) < 12:
        return "Password must be at least 12 characters."
    if len(pw) > 128:
        return "Password is too long (max 128 characters)."
    low = pw.lower()
    if low in COMMON_PASSWORDS:
        return "That password is too common. Try a long passphrase instead."
    if email:
        local = email.split("@")[0].lower()
        if local and len(local) >= 4 and local in low:
            return "Password must not contain your email."
    if full_name:
        for part in full_name.lower().split():
            if len(part) >= 4 and part in low:
                return "Password must not contain your name."
    if pw.isdigit():
        return "Password must not be all digits."
    if len(set(pw)) < 6:
        return "Password has too little variety — pick something more memorable."
    return None


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def _now():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# JWTs                                                                         #
# --------------------------------------------------------------------------- #
def _base_claims() -> dict:
    return {
        "iss": get_jwt_issuer(),
        "aud": get_jwt_audience(),
    }


def make_access_token(user_id: str, role: str, sid: str) -> str:
    """`sid` is REQUIRED — Sprint 1 binds every access token to a server-side session."""
    payload = {
        **_base_claims(),
        "sub": user_id,
        "role": role,
        "type": "access",
        "sid": sid,
        "jti": uuid.uuid4().hex,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(minutes=ACCESS_TTL_MIN)).timestamp()),
    }
    return jwt.encode(payload, assert_valid_secret(), algorithm=JWT_ALGO)


def make_refresh_token(user_id: str, sid: str) -> str:
    """`sid` is REQUIRED. Sprint 2 will add refresh-family rotation; Sprint 1 only binds."""
    payload = {
        **_base_claims(),
        "sub": user_id,
        "type": "refresh",
        "sid": sid,
        "jti": uuid.uuid4().hex,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(days=REFRESH_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(payload, assert_valid_secret(), algorithm=JWT_ALGO)


def decode_token(token: str, expected_type: Optional[str] = None) -> dict:
    """Validates signature, exp, iss, aud. Optionally verifies token type.
    Session revocation is enforced by the caller via db lookup on `sid`."""
    try:
        payload = jwt.decode(
            token,
            assert_valid_secret(),
            algorithms=[JWT_ALGO],
            issuer=get_jwt_issuer(),
            audience=get_jwt_audience(),
            options={"require": ["exp", "iat", "iss", "aud", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Invalid token issuer")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except jwt.MissingRequiredClaimError as e:
        raise HTTPException(status_code=401, detail=f"Token missing required claim: {e}")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if expected_type and payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail=f"Not a {expected_type} token")
    return payload


# --------------------------------------------------------------------------- #
# MFA                                                                          #
# --------------------------------------------------------------------------- #
def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def mfa_provisioning_uri(secret: str, email: str, issuer: str = "NatMedSol") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_mfa(secret: str, token: str) -> bool:
    if not secret or not token:
        return False
    try:
        return pyotp.TOTP(secret).verify(token, valid_window=1)
    except Exception:
        return False
