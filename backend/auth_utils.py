import os
import jwt
import bcrypt
import pyotp
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import Depends, HTTPException, status, Header, Request

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me-in-prod-please")
JWT_ALGO = "HS256"
ACCESS_TTL_MIN = 15
REFRESH_TTL_DAYS = 7


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


# NIST SP 800-63B — modern password guidance
# - Minimum 12 chars, up to 128 (bcrypt truncates at 72 anyway)
# - Reject the top common passwords + trivial patterns
# - NO forced rotation, NO complex-composition rules (proven counterproductive)
COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwerty", "qwertyuiop", "letmein", "welcome", "welcome1", "iloveyou",
    "admin", "administrator", "changeme", "changeme1", "monkey", "dragon",
    "abc123", "test1234", "passw0rd", "p@ssw0rd", "master", "shadow",
    "sunshine", "princess", "football", "baseball", "starwars",
    "natmedsol", "wellness", "ravello",
}


def validate_password_strength(pw: str, email: str = "", full_name: str = "") -> Optional[str]:
    """Return None if OK, else a human-readable failure reason."""
    if not pw or len(pw) < 12:
        return "Password must be at least 12 characters."
    if len(pw) > 128:
        return "Password is too long (max 128 characters)."
    low = pw.lower()
    if low in COMMON_PASSWORDS:
        return "That password is too common. Try a long passphrase instead."
    # Reject if it contains the user's email local-part or full name
    if email:
        local = email.split("@")[0].lower()
        if local and len(local) >= 4 and local in low:
            return "Password must not contain your email."
    if full_name:
        for part in full_name.lower().split():
            if len(part) >= 4 and part in low:
                return "Password must not contain your name."
    # Reject trivial keyboard/date patterns
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


def make_access_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(minutes=ACCESS_TTL_MIN)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def make_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(days=REFRESH_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


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
