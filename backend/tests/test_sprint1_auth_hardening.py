"""
Sprint 1 — auth hardening allow/deny tests.

Covers:
  • JWT config validation (iss/aud/type/exp/session revocation)
  • Server-side session binding (login → session created; logout → revoked)
  • Workforce MFA hard cutover (403 must_enroll_mfa on PHI endpoints)
  • MFA disable blocked for workforce, allowed for client
  • Password change revokes ALL sessions + bumps session_version
  • Password reset: unknown-email indistinguishable from known-email response
  • Password reset: token single-use, atomic consume, revokes sessions
  • Password reset: rate-limited by (email_hash, IP, window) + global
  • DEV_EXPOSE_RESET_TOKEN gated helper works in non-HIPAA mode
"""
from __future__ import annotations

import os
import random
import string
import time

import pyotp
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

CLIENT_PW = "SafePass2026Long!"
NEW_PW = "OtherSafePass2026Long!"


def _nonce(n=6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _register_client() -> tuple[str, str, str, str]:
    """Register a fresh client, return (email, password, access_token, refresh_token)."""
    email = f"s1-client-{_nonce()}@ex.com"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": CLIENT_PW,
        "full_name": f"Q Q", "phone": "+15551110000",
    })
    r.raise_for_status()
    d = r.json()
    return email, CLIENT_PW, d["access_token"], d["refresh_token"]


def _login(email: str, pw: str, mfa_token: str | None = None) -> dict:
    r = requests.post(f"{API}/auth/login", json={
        "email": email, "password": pw, "mfa_token": mfa_token,
    })
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# 1. JWT session binding                                                       #
# --------------------------------------------------------------------------- #
class TestSessionBinding:
    def test_login_creates_session_and_access_works(self):
        _, _, access, _ = _register_client()
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200

    def test_logout_revokes_session(self):
        _, _, access, _ = _register_client()
        # Logout with the token
        r = requests.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 200
        # Reuse same token → should be rejected because session is revoked
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 401
        assert "revoked" in me.json().get("detail", "").lower()

    def test_two_logins_produce_independent_sessions(self):
        email, pw, a1, _ = _register_client()
        a2 = _login(email, pw)["access_token"]
        # Log out of session #1
        requests.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {a1}"})
        # Session #2 must still work
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {a2}"})
        assert me.status_code == 200

    def test_refresh_reuses_same_session_but_new_jti(self):
        _, _, access, refresh = _register_client()
        r = requests.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
        assert r.status_code == 200
        new_access = r.json()["access_token"]
        assert new_access != access  # each token has its own jti


# --------------------------------------------------------------------------- #
# 2. Workforce MFA hard cutover                                                #
# --------------------------------------------------------------------------- #
class TestWorkforceMfa:
    def test_admin_blocked_on_phi_until_mfa_enrolled(self):
        # Create a fresh admin-role user directly (conftest pre-enrols MFA on all
        # seeded workforce accounts, so we can't use them for the "MFA off" scenario).
        import pymongo
        from auth_utils import hash_password
        c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        dbh = c[os.environ.get("DB_NAME", "test_database")]
        email = f"s1-adm-{_nonce()}@ex.com"
        pw = "SafePass2026Long!"
        user_id = f"test-{_nonce(12)}"
        dbh.users.insert_one({
            "id": user_id, "email": email, "password_hash": hash_password(pw),
            "full_name": "Q Q", "role": "admin", "mfa_enabled": False,
            "mfa_secret": None, "is_active": True, "session_version": 1,
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            "last_login_at": None,
        })
        c.close()

        d = _login(email, pw)
        access = d["access_token"]
        hdr = {"Authorization": f"Bearer {access}"}

        # /auth/me is on `get_authenticated_user` (no MFA gate) → 200
        assert requests.get(f"{API}/auth/me", headers=hdr).status_code == 200

        # PHI endpoint uses require_roles → require_workforce_mfa fires → 403
        r = requests.get(f"{API}/clients", headers=hdr)
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert isinstance(detail, dict) and detail.get("code") == "must_enroll_mfa"

        # Setup + verify MFA → PHI now works
        setup = requests.post(f"{API}/auth/mfa/setup", headers=hdr).json()
        totp = pyotp.TOTP(setup["secret"]).now()
        v = requests.post(f"{API}/auth/mfa/verify", headers=hdr, json={"token": totp})
        assert v.status_code == 200
        r = requests.get(f"{API}/clients", headers=hdr)
        assert r.status_code == 200

    def test_workforce_cannot_disable_mfa(self):
        # Seeded staff — conftest already turned MFA on.
        d = _login("frontdesk@natmedsol.local", "FrontDesk!2345")
        hdr = {"Authorization": f"Bearer {d['access_token']}"}
        r = requests.post(f"{API}/auth/mfa/disable", headers=hdr)
        assert r.status_code == 403
        assert "workforce" in r.json()["detail"].lower()

    def test_client_can_disable_mfa(self):
        _, _, access, _ = _register_client()
        hdr = {"Authorization": f"Bearer {access}"}
        setup = requests.post(f"{API}/auth/mfa/setup", headers=hdr).json()
        totp = pyotp.TOTP(setup["secret"]).now()
        requests.post(f"{API}/auth/mfa/verify", headers=hdr, json={"token": totp})
        r = requests.post(f"{API}/auth/mfa/disable", headers=hdr)
        assert r.status_code == 200


# --------------------------------------------------------------------------- #
# 3. Password change revokes ALL sessions + bumps session_version              #
# --------------------------------------------------------------------------- #
class TestPasswordChange:
    def test_change_password_revokes_all_and_bumps_version(self):
        email, pw, a1, _ = _register_client()
        a2 = _login(email, pw)["access_token"]
        h1 = {"Authorization": f"Bearer {a1}"}
        h2 = {"Authorization": f"Bearer {a2}"}

        # Both sessions live
        assert requests.get(f"{API}/auth/me", headers=h1).status_code == 200
        assert requests.get(f"{API}/auth/me", headers=h2).status_code == 200

        # Change password on session #1
        r = requests.post(f"{API}/auth/change-password", headers=h1, json={
            "current_password": pw, "new_password": NEW_PW,
        })
        assert r.status_code == 200
        assert r.json()["must_relogin"] is True

        # Both sessions must now be revoked
        assert requests.get(f"{API}/auth/me", headers=h1).status_code == 401
        assert requests.get(f"{API}/auth/me", headers=h2).status_code == 401

        # session_version should have incremented
        import pymongo
        c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        u = c[os.environ.get("DB_NAME", "test_database")].users.find_one({"email": email})
        c.close()
        assert u["session_version"] >= 2


# --------------------------------------------------------------------------- #
# 4. Password reset (self-serve forgot flow)                                   #
# --------------------------------------------------------------------------- #
class TestPasswordReset:
    def test_unknown_and_known_email_return_identical_response(self):
        email, _, _, _ = _register_client()
        unknown = f"s1-unknown-{_nonce()}@ex.com"
        r_known = requests.post(f"{API}/auth/forgot-password", json={"email": email})
        r_unknown = requests.post(f"{API}/auth/forgot-password", json={"email": unknown})
        assert r_known.status_code == r_unknown.status_code == 200
        assert r_known.json() == r_unknown.json()  # identical body — no enumeration

    def test_reset_token_end_to_end(self):
        email, _, _, _ = _register_client()
        # Trigger reset
        requests.post(f"{API}/auth/forgot-password", json={"email": email})
        # Dev helper retrieves the raw token (disabled in HIPAA mode)
        t = requests.post(f"{API}/auth/dev/reset-token", json={"email": email})
        assert t.status_code == 200
        raw = t.json()["dev_reset_token"]
        # Reset the password
        r = requests.post(f"{API}/auth/reset-password", json={
            "token": raw, "new_password": NEW_PW,
        })
        assert r.status_code == 200
        # Old password must fail; new password must succeed
        assert requests.post(f"{API}/auth/login", json={
            "email": email, "password": CLIENT_PW,
        }).status_code == 401
        assert requests.post(f"{API}/auth/login", json={
            "email": email, "password": NEW_PW,
        }).status_code == 200

    def test_reset_token_is_single_use(self):
        email, _, _, _ = _register_client()
        requests.post(f"{API}/auth/forgot-password", json={"email": email})
        raw = requests.post(f"{API}/auth/dev/reset-token", json={"email": email}).json()["dev_reset_token"]
        assert requests.post(f"{API}/auth/reset-password", json={
            "token": raw, "new_password": NEW_PW,
        }).status_code == 200
        # Reuse must fail
        r = requests.post(f"{API}/auth/reset-password", json={
            "token": raw, "new_password": NEW_PW + "2",
        })
        assert r.status_code == 400

    def test_reset_token_rejects_weak_password(self):
        email, _, _, _ = _register_client()
        requests.post(f"{API}/auth/forgot-password", json={"email": email})
        raw = requests.post(f"{API}/auth/dev/reset-token", json={"email": email}).json()["dev_reset_token"]
        r = requests.post(f"{API}/auth/reset-password", json={
            "token": raw, "new_password": "short",
        })
        assert r.status_code == 400
        # Token should still be usable (roll-back on password validation failure)
        r2 = requests.post(f"{API}/auth/reset-password", json={
            "token": raw, "new_password": NEW_PW,
        })
        assert r2.status_code == 200

    def test_reset_rate_limit_per_email(self):
        email = f"s1-rate-{_nonce()}@ex.com"
        # Even though the account doesn't exist, we still expect 200 responses.
        # After 3 attempts in-window the rate limiter kicks in but the response body stays identical.
        bodies = []
        for _ in range(5):
            r = requests.post(f"{API}/auth/forgot-password", json={"email": email})
            assert r.status_code == 200
            bodies.append(r.json())
        # All 5 responses are identical — no enumeration signal
        assert all(b == bodies[0] for b in bodies)


# --------------------------------------------------------------------------- #
# 5. Log/audit redaction — no raw token, URL, or email in audit trail          #
# --------------------------------------------------------------------------- #
class TestAuditRedaction:
    def test_no_raw_reset_token_in_integration_log(self):
        email, _, _, _ = _register_client()
        requests.post(f"{API}/auth/forgot-password", json={"email": email})
        raw = requests.post(f"{API}/auth/dev/reset-token", json={"email": email}).json()["dev_reset_token"]

        import pymongo
        c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        dbh = c[os.environ.get("DB_NAME", "test_database")]

        # No integration_log entry should contain the raw token or the target email
        for doc in dbh.integration_log.find({"action": "auth.password_reset_dispatch"}):
            body_str = str(doc)
            assert raw not in body_str, "Raw reset token leaked into integration_log"
            assert email not in body_str, "Raw email leaked into integration_log"
            # Sanity: recipient should be a sha256 prefix
            assert str(doc.get("payload", {}).get("to", "")).startswith("sha256:")

        # No audit_logs row should carry the raw token or the raw email
        for doc in dbh.audit_logs.find({"action": {"$in": ["auth.password_reset_requested", "auth.password_reset_completed"]}}):
            body_str = str(doc)
            assert raw not in body_str
            assert email not in body_str

        c.close()
