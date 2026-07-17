"""
Cryptographic + auth helpers.

Sprint 1 changes:
- JWTs now include `iss`, `aud`, `jti`, and `sid` (session id) claims.
- `decode_token()` enforces `iss`, `aud`, and token type in addition to signature + expiry.
- `assert_valid_secret()` validates JWT_SECRET entropy (Shannon > 3.5 bits/char AND ≥ 32 chars).
- No default `JWT_SECRET` in HIPAA mode — startup fails hard if unset (see deps.py).
- MFA TOTP secrets are AES-256-GCM encrypted at rest via `encrypt_mfa_secret` /
  `decrypt_mfa_secret`. Encryption key comes from `MFA_ENC_KEY_B64` env var
  (32 random bytes, base64-url), never from Mongo.
"""
import base64
import math
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
import pyotp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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


def make_access_token(user_id: str, role: str, sid: str, session_version: int = 1) -> str:
    """`sid` is REQUIRED — Sprint 1 binds every access token to a server-side session.
    Sprint 2 adds `sv` (session_version) so revocation via version-bump is detectable."""
    payload = {
        **_base_claims(),
        "sub": user_id,
        "role": role,
        "type": "access",
        "sid": sid,
        "sv": int(session_version),
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
_MFA_CT_PREFIX = "enc-v1:"  # marks AES-GCM ciphertext so we can support in-flight migration


def _mfa_key() -> bytes:
    """Load and validate the MFA encryption key (32 bytes, base64-url).
    In HIPAA mode: required. In dev: falls back to a deterministic key so
    existing tests keep working when the env var is unset."""
    v = os.environ.get("MFA_ENC_KEY_B64", "")
    if v:
        try:
            key = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))
        except Exception as e:
            raise RuntimeError(f"MFA_ENC_KEY_B64 is not valid base64: {e}")
        if len(key) != 32:
            raise RuntimeError(f"MFA_ENC_KEY_B64 must decode to exactly 32 bytes (got {len(key)}).")
        return key
    if _hipaa_mode():
        raise RuntimeError("HIPAA_MODE=on: MFA_ENC_KEY_B64 is required (32 random bytes, base64).")
    # Deterministic dev key — NEVER used when HIPAA_MODE=on.
    return b"dev-mfa-key-DO-NOT-USE-IN-PROD!!"


def encrypt_mfa_secret(plaintext: str) -> str:
    """AES-256-GCM encrypt a TOTP secret. Returns 'enc-v1:<base64-nonce||ct||tag>'."""
    if not plaintext:
        return ""
    key = _mfa_key()
    nonce = os.urandom(12)  # 96-bit GCM nonce
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data=b"mfa_secret")
    blob = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
    return _MFA_CT_PREFIX + blob


def decrypt_mfa_secret(stored: str) -> str:
    """Reverse of `encrypt_mfa_secret`. Also transparently returns plaintext when
    the value predates the encrypted-at-rest migration (i.e. lacks the prefix)."""
    if not stored:
        return ""
    if not stored.startswith(_MFA_CT_PREFIX):
        # Legacy plaintext — will be re-encrypted by migration script on next boot.
        return stored
    blob = stored[len(_MFA_CT_PREFIX):]
    raw = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
    if len(raw) < 13:
        raise RuntimeError("MFA ciphertext too short")
    nonce, ct = raw[:12], raw[12:]
    pt = AESGCM(_mfa_key()).decrypt(nonce, ct, associated_data=b"mfa_secret")
    return pt.decode("utf-8")


def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def mfa_provisioning_uri(secret: str, email: str, issuer: str = "NatMedSol") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_mfa(secret_stored: str, token: str) -> bool:
    """`secret_stored` may be ciphertext (Sprint 1b) or legacy plaintext."""
    if not secret_stored or not token:
        return False
    try:
        plaintext = decrypt_mfa_secret(secret_stored)
        return pyotp.TOTP(plaintext).verify(token, valid_window=1)
    except Exception:
        return False
