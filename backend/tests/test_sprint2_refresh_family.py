"""
Sprint 2 — Opaque refresh cookie, atomic rotation with concurrency grace,
family reuse detection, workforce session-limit continuation, central
revocation, idle-before-touch, absolute cap, session_version staleness.

All tests use requests.Session() for cookie-jar handling.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pymongo
import pyotp
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

FIXTURE_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
ADMIN_EMAIL = "tallyravello@gmail.com"
ADMIN_PW = "TEST123"


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _mongo():
    return pymongo.MongoClient(MONGO_URL)[DB_NAME]


def _totp():
    return pyotp.TOTP(FIXTURE_TOTP_SECRET).now()


def _fresh_client(session: requests.Session):
    email = f"s2c-{uuid.uuid4().hex[:8]}@ex.com"
    r = session.post(f"{BASE_URL}/api/auth/register", json={
        "email": email, "password": "SafePass2026Long!", "full_name": "Q Q"
    })
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return email, data


def _admin_login(session: requests.Session):
    # conftest.py monkey-patches Session.post to auto-inject TOTP for seeded workforce.
    r = session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()


def _clear_admin_sessions():
    """Ensure the seeded admin has NO active sessions before each test that
    needs a predictable session count."""
    dbh = _mongo()
    u = dbh.users.find_one({"email": ADMIN_EMAIL}, {"id": 1})
    if not u:
        return
    dbh.user_sessions.update_many(
        {"user_id": u["id"], "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc),
                  "revoke_reason": "test_reset"}},
    )
    dbh.refresh_tokens.update_many(
        {"user_id": u["id"], "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc),
                  "revoke_reason": "test_reset"}},
    )


# --------------------------------------------------------------------------- #
# 1. Opaque refresh cookie: JSON must NOT contain refresh_token; cookie MUST  #
# --------------------------------------------------------------------------- #
class TestOpaqueRefreshCookieDelivery:
    def test_client_register_returns_no_refresh_in_body(self):
        s = requests.Session()
        _, data = _fresh_client(s)
        assert "access_token" in data
        assert data["access_token"], "access_token empty"
        # refresh_token must be absent OR empty string
        assert not data.get("refresh_token"), (
            f"refresh_token leaked in body: {data.get('refresh_token')!r}"
        )
        # Cookie present with correct path
        cookie = next((c for c in s.cookies if c.name == "nms_rt"), None)
        assert cookie is not None, "nms_rt cookie missing after register"
        assert cookie.value, "nms_rt cookie value empty"
        assert cookie.path == "/api/auth/refresh", (
            f"nms_rt cookie path is {cookie.path!r}, expected /api/auth/refresh"
        )

    def test_client_login_returns_no_refresh_in_body(self):
        s = requests.Session()
        email, _ = _fresh_client(s)
        s.cookies.clear()
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": email, "password": "SafePass2026Long!"})
        assert r.status_code == 200
        data = r.json()
        assert data.get("access_token")
        assert not data.get("refresh_token"), "refresh_token leaked in login body"
        cookie = next((c for c in s.cookies if c.name == "nms_rt"), None)
        assert cookie is not None
        assert cookie.path == "/api/auth/refresh"

    def test_set_cookie_header_has_httponly_flag(self):
        """Directly inspect Set-Cookie for HttpOnly + SameSite=Lax."""
        s = requests.Session()
        email, _ = _fresh_client(s)
        s.cookies.clear()
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": email, "password": "SafePass2026Long!"})
        # requests exposes raw Set-Cookie via r.raw or r.headers (multi-header lost)
        set_cookie = r.headers.get("Set-Cookie") or ""
        assert "nms_rt=" in set_cookie
        assert "HttpOnly" in set_cookie, f"HttpOnly missing: {set_cookie!r}"
        assert "Path=/api/auth/refresh" in set_cookie, f"Path wrong: {set_cookie!r}"
        # SameSite=Lax (case may vary)
        assert "samesite" in set_cookie.lower(), f"SameSite missing: {set_cookie!r}"


# --------------------------------------------------------------------------- #
# 2. Cookie path scoping — /api/clients must NOT receive nms_rt                #
# --------------------------------------------------------------------------- #
class TestCookiePathScoping:
    def test_nms_rt_not_sent_to_non_refresh_path(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        access = data["access_token"]
        # Confirm the cookie exists
        assert any(c.name == "nms_rt" for c in s.cookies)
        # Now hit /api/clients with the Session — the cookie jar decides whether
        # to send nms_rt based on the cookie's Path attribute.
        prepped = s.prepare_request(requests.Request(
            "GET", f"{BASE_URL}/api/clients",
            headers={"Authorization": f"Bearer {access}"},
        ))
        # Inspect the outgoing Cookie header on the prepared request.
        outgoing = prepped.headers.get("Cookie", "")
        assert "nms_rt" not in outgoing, (
            f"nms_rt cookie was going to be sent to /api/clients: {outgoing!r}"
        )


# --------------------------------------------------------------------------- #
# 3. Atomic rotation                                                          #
# --------------------------------------------------------------------------- #
class TestAtomicRotation:
    def test_refresh_rotates_access_and_cookie(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        old_access = data["access_token"]
        old_cookie = next(c for c in s.cookies if c.name == "nms_rt").value

        r = s.post(f"{BASE_URL}/api/auth/refresh")
        assert r.status_code == 200, f"refresh failed: {r.status_code} {r.text}"
        j = r.json()
        assert j.get("access_token"), "new access_token missing"
        assert j["access_token"] != old_access, "access_token was not rotated"

        new_cookie = next(c for c in s.cookies if c.name == "nms_rt").value
        assert new_cookie != old_cookie, "nms_rt cookie was not rotated"


# --------------------------------------------------------------------------- #
# 4. Concurrency grace — old cookie within 5s → 409                            #
# --------------------------------------------------------------------------- #
class TestConcurrencyGrace:
    def test_old_cookie_within_grace_returns_409_no_family_burn(self):
        s = requests.Session()
        _, _ = _fresh_client(s)
        old_cookie = next(c for c in s.cookies if c.name == "nms_rt").value

        # First refresh — winner.
        r1 = s.post(f"{BASE_URL}/api/auth/refresh")
        assert r1.status_code == 200
        winner_cookie = next(c for c in s.cookies if c.name == "nms_rt").value
        assert winner_cookie != old_cookie

        # Immediately replay the OLD cookie in a separate session (same UA).
        s2 = requests.Session()
        s2.headers.update({"User-Agent": s.headers.get("User-Agent", "python-requests/2")})
        s2.cookies.set("nms_rt", old_cookie, domain=BASE_URL.split("://",1)[1].split("/")[0],
                       path="/api/auth/refresh")
        r2 = s2.post(f"{BASE_URL}/api/auth/refresh")
        assert r2.status_code == 409, (
            f"expected 409 concurrency_retry, got {r2.status_code} {r2.text}"
        )
        assert "concurrency_retry" in r2.text, f"body: {r2.text}"

        # Family must NOT be burned — the winner's cookie still works.
        r3 = s.post(f"{BASE_URL}/api/auth/refresh")
        assert r3.status_code == 200, (
            f"successor cookie should still work but got {r3.status_code} {r3.text}"
        )

    def test_family_not_revoked_after_grace_409(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        old_cookie = next(c for c in s.cookies if c.name == "nms_rt").value
        r1 = s.post(f"{BASE_URL}/api/auth/refresh")
        assert r1.status_code == 200
        # replay old within grace
        s2 = requests.Session()
        s2.cookies.set("nms_rt", old_cookie,
                       domain=BASE_URL.split("://",1)[1].split("/")[0],
                       path="/api/auth/refresh")
        s2.post(f"{BASE_URL}/api/auth/refresh")

        # DB check — family should have at least one non-revoked row.
        dbh = _mongo()
        u = dbh.users.find_one({"email": email}, {"id": 1})
        active = dbh.refresh_tokens.count_documents({
            "user_id": u["id"], "revoked_at": None
        })
        assert active >= 1, "family was burned during concurrency grace — regression"


# --------------------------------------------------------------------------- #
# 5. Reuse detection outside grace window                                      #
# --------------------------------------------------------------------------- #
class TestReuseDetection:
    def test_replay_after_grace_burns_family_and_session(self):
        # Speed up: instead of sleeping 6s, we DB-tamper `used_at` on the parent
        # token to 30s ago, then present the old cookie.
        s = requests.Session()
        email, data = _fresh_client(s)
        old_cookie = next(c for c in s.cookies if c.name == "nms_rt").value

        r1 = s.post(f"{BASE_URL}/api/auth/refresh")
        assert r1.status_code == 200
        successor_access = r1.json()["access_token"]

        # Tamper `used_at` on the parent (now-used) token to 30s ago.
        dbh = _mongo()
        import hashlib
        parent_hash = hashlib.sha256(old_cookie.encode()).hexdigest()
        past = datetime.now(timezone.utc) - timedelta(seconds=30)
        r = dbh.refresh_tokens.update_one(
            {"token_hash": parent_hash},
            {"$set": {"used_at": past}},
        )
        assert r.modified_count == 1, "parent token not found in DB"

        # Replay the old cookie — should be treated as confirmed reuse.
        s2 = requests.Session()
        s2.cookies.set("nms_rt", old_cookie,
                       domain=BASE_URL.split("://",1)[1].split("/")[0],
                       path="/api/auth/refresh")
        r2 = s2.post(f"{BASE_URL}/api/auth/refresh")
        assert r2.status_code == 401, (
            f"expected 401 after reuse, got {r2.status_code} {r2.text}"
        )

        # Family fully revoked with revoke_reason='reuse_detected' (or reuse_after_revoke).
        u = dbh.users.find_one({"email": email}, {"id": 1})
        active = dbh.refresh_tokens.count_documents({
            "user_id": u["id"], "revoked_at": None
        })
        assert active == 0, f"family not fully revoked: {active} tokens still active"

        any_reuse = dbh.refresh_tokens.count_documents({
            "user_id": u["id"],
            "revoke_reason": {"$in": ["reuse_detected", "reuse_after_revoke"]},
        })
        assert any_reuse >= 1, "no refresh_tokens row has revoke_reason=reuse_*"

        # /auth/me with the successor access token should now fail.
        r3 = requests.get(f"{BASE_URL}/api/auth/me",
                          headers={"Authorization": f"Bearer {successor_access}"})
        assert r3.status_code == 401, (
            f"successor access token should be dead after family burn: {r3.status_code} {r3.text}"
        )


# --------------------------------------------------------------------------- #
# 6. Central revocation                                                        #
# --------------------------------------------------------------------------- #
class TestCentralRevocation:
    def test_change_password_revokes_all_sessions(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        access = data["access_token"]

        # Change password.
        r = s.post(f"{BASE_URL}/api/auth/change-password",
                   headers={"Authorization": f"Bearer {access}"},
                   json={"current_password": "SafePass2026Long!",
                         "new_password": "AnotherSafe2026!!"})
        assert r.status_code == 200, f"change-password failed: {r.status_code} {r.text}"

        # Old access token now dead (session revoked OR session_version stale).
        r2 = requests.get(f"{BASE_URL}/api/auth/me",
                          headers={"Authorization": f"Bearer {access}"})
        assert r2.status_code == 401, (
            f"old access should be 401 after change-password, got {r2.status_code}"
        )

        # Refresh cookie should also be dead.
        r3 = s.post(f"{BASE_URL}/api/auth/refresh")
        assert r3.status_code == 401, (
            f"refresh should be dead after change-password, got {r3.status_code}"
        )

    def test_logout_all_revokes_everything(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        access = data["access_token"]

        r = s.post(f"{BASE_URL}/api/auth/logout-all",
                   headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 200, f"logout-all failed: {r.status_code} {r.text}"

        r2 = requests.get(f"{BASE_URL}/api/auth/me",
                          headers={"Authorization": f"Bearer {access}"})
        assert r2.status_code == 401

    def test_list_sessions_returns_sanitized(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        access = data["access_token"]
        r = s.get(f"{BASE_URL}/api/auth/sessions",
                  headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        sessions = r.json()
        assert isinstance(sessions, list)
        assert len(sessions) >= 1
        current = [x for x in sessions if x.get("is_current")]
        assert len(current) == 1, f"exactly one is_current expected, got {len(current)}"
        for s_row in sessions:
            # No raw IP / no full user-agent leaked.
            assert "ip" not in s_row and "ip_first" not in s_row and "ip_last" not in s_row
            assert "user_agent" not in s_row
            assert "device_label" in s_row
            assert "session_id" in s_row

    def test_delete_session_revokes_it(self):
        # Create a second session for the same client user, then delete it.
        s1 = requests.Session()
        email, data1 = _fresh_client(s1)
        access1 = data1["access_token"]

        s2 = requests.Session()
        r = s2.post(f"{BASE_URL}/api/auth/login",
                    json={"email": email, "password": "SafePass2026Long!"})
        assert r.status_code == 200
        access2 = r.json()["access_token"]

        # From session1, list sessions and find session2's id.
        sess = s1.get(f"{BASE_URL}/api/auth/sessions",
                      headers={"Authorization": f"Bearer {access1}"}).json()
        other = [x for x in sess if not x.get("is_current")]
        assert len(other) >= 1, f"expected at least 1 non-current session, got {sess}"
        target_sid = other[0]["session_id"]

        r = s1.delete(f"{BASE_URL}/api/auth/sessions/{target_sid}",
                      headers={"Authorization": f"Bearer {access1}"})
        assert r.status_code == 200

        # session2's access token should now be dead.
        r2 = requests.get(f"{BASE_URL}/api/auth/me",
                          headers={"Authorization": f"Bearer {access2}"})
        assert r2.status_code == 401


# --------------------------------------------------------------------------- #
# 7. Idle-before-touch                                                         #
# --------------------------------------------------------------------------- #
class TestIdleBeforeTouch:
    def test_idle_20min_rejects_before_touch(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        access = data["access_token"]

        # First hit /auth/me to make sure the session works.
        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 200

        # DB-tamper: set last_used_at to 20 min ago on this session.
        dbh = _mongo()
        u = dbh.users.find_one({"email": email}, {"id": 1})
        past = datetime.now(timezone.utc) - timedelta(minutes=20)
        # There should be exactly 1 active session for this fresh user.
        session_doc = dbh.user_sessions.find_one(
            {"user_id": u["id"], "revoked_at": None}
        )
        assert session_doc is not None
        # Client role: idle timeout is CLIENT_IDLE_TIMEOUT_MIN=60. Force 90.
        # Wait — clients get 60-min idle. Set to 90 min to be safely past.
        past = datetime.now(timezone.utc) - timedelta(minutes=90)
        dbh.user_sessions.update_one(
            {"id": session_doc["id"]},
            {"$set": {"last_used_at": past,
                      "idle_timeout_minutes": session_doc.get("idle_timeout_minutes", 60)}},
        )

        # Hit /auth/me → should be 401 idle_expired.
        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 401, f"expected 401 idle, got {r.status_code} {r.text}"
        assert "idle" in r.text.lower() or "idle_expired" in r.text or "session_idle_expired" in r.text, \
            f"detail should mention idle: {r.text!r}"

        # The stored last_used_at MUST NOT have been bumped by the failing call.
        after = dbh.user_sessions.find_one({"id": session_doc["id"]})
        # It's now revoked; check last_used_at is still ~90min old (not now).
        lu = after.get("last_used_at")
        if lu and lu.tzinfo is None:
            lu = lu.replace(tzinfo=timezone.utc)
        # Allow a few seconds of slack for clock drift, but must still be old.
        assert lu < datetime.now(timezone.utc) - timedelta(minutes=60), (
            f"last_used_at was bumped despite idle rejection: {lu}"
        )


# --------------------------------------------------------------------------- #
# 8. Absolute cap                                                              #
# --------------------------------------------------------------------------- #
class TestAbsoluteCap:
    def test_absolute_expired_rejects_even_with_fresh_last_used(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        access = data["access_token"]

        dbh = _mongo()
        u = dbh.users.find_one({"email": email}, {"id": 1})
        session_doc = dbh.user_sessions.find_one({"user_id": u["id"], "revoked_at": None})
        assert session_doc

        now = datetime.now(timezone.utc)
        dbh.user_sessions.update_one(
            {"id": session_doc["id"]},
            {"$set": {"absolute_expires_at": now - timedelta(seconds=5),
                      "last_used_at": now}},
        )

        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 401, f"expected 401 absolute, got {r.status_code} {r.text}"
        assert "absolute" in r.text.lower(), f"detail should mention absolute: {r.text!r}"


# --------------------------------------------------------------------------- #
# 9. session_version staleness                                                 #
# --------------------------------------------------------------------------- #
class TestSessionVersionStaleness:
    def test_access_token_becomes_stale_after_password_change(self):
        s = requests.Session()
        email, data = _fresh_client(s)
        old_access = data["access_token"]

        # change-password bumps session_version and revokes all sessions.
        r = s.post(f"{BASE_URL}/api/auth/change-password",
                   headers={"Authorization": f"Bearer {old_access}"},
                   json={"current_password": "SafePass2026Long!",
                         "new_password": "SecondSafe2026!!"})
        assert r.status_code == 200

        # Re-login → gets a NEW access token issued at bumped session_version.
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": email, "password": "SecondSafe2026!!"})
        assert r.status_code == 200
        new_access = r.json()["access_token"]

        # New access works.
        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {new_access}"})
        assert r.status_code == 200

        # Old access from BEFORE the bump must NOT work (already covered by
        # session revocation, but this asserts it explicitly).
        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {old_access}"})
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# 10. Workforce active-session cap → continuation flow                         #
# --------------------------------------------------------------------------- #
class TestWorkforceSessionLimit:
    def test_workforce_cap_returns_continuation_ticket(self):
        """Fill the cap with synthetic active sessions inserted directly in DB
        (much faster than 200 real logins), then attempt to log in."""
        _clear_admin_sessions()
        dbh = _mongo()
        u = dbh.users.find_one({"email": ADMIN_EMAIL}, {"id": 1})
        cap = int(os.environ.get("MAX_ACTIVE_WORKFORCE_SESSIONS", "200"))
        now = datetime.now(timezone.utc)
        rows = []
        for i in range(cap):
            rows.append({
                "id": uuid.uuid4().hex,
                "user_id": u["id"],
                "created_at": now - timedelta(hours=1) + timedelta(seconds=i),
                "last_used_at": now,
                "expires_at": now + timedelta(hours=6),
                "idle_timeout_minutes": 15,
                "absolute_expires_at": now + timedelta(hours=6),
                "revoked_at": None,
                "revoke_reason": None,
                "session_version": 1,
                "ip_first": "127.0.0.1", "ip_last": "127.0.0.1",
                "user_agent": "python-requests/2.x (Macintosh; Chrome)",
                "mfa_satisfied_at": now,
                "family_id": uuid.uuid4().hex,
            })
        dbh.user_sessions.insert_many(rows)

        try:
            # Now attempt login — the conftest patch auto-injects TOTP.
            s = requests.Session()
            r = s.post(f"{BASE_URL}/api/auth/login",
                       json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
            assert r.status_code == 409, (
                f"expected 409 at workforce cap, got {r.status_code} {r.text}"
            )
            detail = r.json().get("detail") or {}
            assert isinstance(detail, dict), f"detail must be dict, got: {detail!r}"
            assert detail.get("code") == "active_session_limit_exceeded"
            ticket = detail.get("continuation_ticket")
            assert ticket, "continuation_ticket missing"
            active = detail.get("active_sessions") or []
            assert isinstance(active, list) and len(active) > 0
            # Sanitized: no raw IPs / no full user-agent.
            for row in active:
                assert "ip" not in row and "ip_first" not in row and "ip_last" not in row
                assert "user_agent" not in row
                assert "device_label" in row

            # Continue with a chosen session id.
            revoke_sid = active[0]["session_id"]
            r2 = s.post(f"{BASE_URL}/api/auth/login/continue",
                        json={"continuation_ticket": ticket,
                              "revoke_session_id": revoke_sid})
            assert r2.status_code == 200, (
                f"login/continue failed: {r2.status_code} {r2.text}"
            )
            j = r2.json()
            assert j.get("access_token")
            # Cookie set
            cookie = next((c for c in s.cookies if c.name == "nms_rt"), None)
            assert cookie is not None
        finally:
            _clear_admin_sessions()


# --------------------------------------------------------------------------- #
# 11. Client evict-oldest                                                      #
# --------------------------------------------------------------------------- #
class TestClientEvictOldest:
    def test_client_login_at_cap_evicts_oldest_and_returns_notice(self):
        s = requests.Session()
        email, _ = _fresh_client(s)
        dbh = _mongo()
        u = dbh.users.find_one({"email": email}, {"id": 1})
        cap = int(os.environ.get("MAX_ACTIVE_CLIENT_SESSIONS", "200"))
        now = datetime.now(timezone.utc)
        # Insert `cap` synthetic sessions with distinct created_at so we know
        # which is oldest.
        rows = []
        for i in range(cap):
            rows.append({
                "id": f"OLD-{i:04d}-{uuid.uuid4().hex[:8]}",
                "user_id": u["id"],
                "created_at": now - timedelta(days=7) + timedelta(minutes=i),
                "last_used_at": now - timedelta(minutes=1),
                "expires_at": now + timedelta(days=1),
                "idle_timeout_minutes": 60,
                "absolute_expires_at": now + timedelta(days=1),
                "revoked_at": None,
                "revoke_reason": None,
                "session_version": 1,
                "ip_first": "127.0.0.1", "ip_last": "127.0.0.1",
                "user_agent": "python-requests/2.x",
                "mfa_satisfied_at": now,
                "family_id": uuid.uuid4().hex,
            })
        # Revoke the auto-created session from register so we're at exactly cap.
        dbh.user_sessions.update_many(
            {"user_id": u["id"], "revoked_at": None},
            {"$set": {"revoked_at": now, "revoke_reason": "test_setup_cleanup"}},
        )
        dbh.user_sessions.insert_many(rows)
        oldest_id = rows[0]["id"]

        # Fresh login — should succeed with notice, oldest evicted.
        s2 = requests.Session()
        r = s2.post(f"{BASE_URL}/api/auth/login",
                    json={"email": email, "password": "SafePass2026Long!"})
        assert r.status_code == 200, (
            f"client login at cap should succeed, got {r.status_code} {r.text}"
        )
        j = r.json()
        assert j.get("access_token")
        assert j.get("notice"), f"'notice' field missing: {j}"

        # Oldest session should now be revoked with reason client_evicted_oldest.
        oldest = dbh.user_sessions.find_one({"id": oldest_id})
        assert oldest is not None
        assert oldest.get("revoked_at") is not None, (
            f"oldest session not revoked; doc={oldest}"
        )
        assert oldest.get("revoke_reason") == "client_evicted_oldest", (
            f"revoke_reason={oldest.get('revoke_reason')!r}"
        )
