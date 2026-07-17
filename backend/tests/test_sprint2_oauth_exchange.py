"""
Sprint 2 — Google OAuth Direct exchange endpoint verification.

Covers the narrow Sprint 2 acceptance criteria for the OAuth completion flow:

  * `/api/auth/google/oauth/exchange` completes without a 500 error.
  * A `user_sessions` record exists after the callback flow.
  * The opaque refresh token is issued ONLY via the `nms_rt` HttpOnly cookie
    (never in JSON body).
  * The access token is returned in the JSON body.
  * The callback path respects idle + absolute session expiration policy.
  * No raw token / OAuth code / email / cookie value appears in captured logs.
  * Password login + `/auth/refresh` flows remain unaffected (regression).

Google's authorize/userinfo endpoints are network-external, so we bypass them
by driving the same code path the callback executes (register a fresh client
user, run `_create_session` via a real password login, then seed an
`oauth_handoffs` row that mirrors what the callback would write). This
exercises the exchange endpoint in isolation while proving the surrounding
session + cookie mechanics behave as designed.
"""
from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pymongo
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

REFRESH_COOKIE = "nms_rt"


def _db():
    return pymongo.MongoClient(MONGO_URL)[DB_NAME]


def _register_client() -> tuple[requests.Session, dict, str]:
    """Register a brand-new client account and return (session, user, access_token)."""
    s = requests.Session()
    email = f"oauthfx_{uuid.uuid4().hex[:10]}@example.com"
    password = "Sprint2Test!23456"
    r = s.post(f"{API}/auth/register", json={
        "email": email, "password": password,
        "full_name": "OAuth Fixture", "phone": "+15555550100",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    return s, body["user"], body["access_token"]


def _seed_handoff(user_id: str, access_token: str, refresh_cookie_value: str,
                  age_seconds: int = 0) -> str:
    handoff_id = secrets.token_urlsafe(24)
    _db().oauth_handoffs.insert_one({
        "handoff_id": handoff_id,
        "user_id": user_id,
        "access_token": access_token,
        "refresh_cookie_value": refresh_cookie_value,
        "created_at": datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        "consumed": False,
    })
    return handoff_id


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #
def test_oauth_exchange_happy_path_delivers_cookie_only_refresh():
    """Callback surrogate → exchange → verify all Sprint 2 invariants."""
    s, user, access = _register_client()
    # The register response already set nms_rt on `s`. Read it, then wipe the
    # session cookie jar to simulate the browser landing on /oauth-complete
    # with a fresh cookie jar (only the handoff id in URL).
    raw_refresh = s.cookies.get(REFRESH_COOKIE)
    assert raw_refresh, "register should set the nms_rt cookie"
    assert len(raw_refresh) >= 32, "opaque refresh token should be sufficiently long"
    s.cookies.clear()

    # The callback would have written this handoff row. Reuse the *same*
    # access + refresh minted from registration — that is exactly what
    # google_oauth_callback stores after calling `_create_session`.
    handoff_id = _seed_handoff(user["id"], access, raw_refresh)

    exch = requests.Session()
    r = exch.post(f"{API}/auth/google/oauth/exchange",
                  json={"handoff_id": handoff_id})
    assert r.status_code == 200, r.text
    body = r.json()

    # -- access token present, refresh token NOT in body ------------------ #
    assert body.get("access_token") == access
    assert "refresh_token" not in body, \
        "Sprint 2 violation: refresh token must NEVER appear in JSON body"
    assert body["user"]["id"] == user["id"]
    assert body["user"]["email"] == user["email"]

    # -- refresh delivered via HttpOnly cookie only ----------------------- #
    set_cookie_header = r.headers.get("set-cookie", "")
    assert REFRESH_COOKIE in set_cookie_header, \
        f"exchange must set the {REFRESH_COOKIE} cookie"
    assert "HttpOnly" in set_cookie_header, "refresh cookie must be HttpOnly"
    assert "SameSite=lax" in set_cookie_header.lower() or \
           "samesite=lax" in set_cookie_header.lower(), \
           "refresh cookie must be SameSite=Lax"
    delivered = exch.cookies.get(REFRESH_COOKIE)
    assert delivered == raw_refresh, "cookie payload must match opaque token"

    # -- user_sessions record exists and honours idle + absolute policy --- #
    db = _db()
    sessions = list(db.user_sessions.find({"user_id": user["id"]}))
    assert len(sessions) >= 1
    sess = sessions[-1]
    assert sess.get("revoked_at") is None
    assert sess.get("absolute_expires_at") is not None
    assert sess.get("idle_timeout_minutes") is not None
    assert sess["absolute_expires_at"].replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    # -- cookie actually powers /auth/refresh (Sprint 2 rotation lives) --- #
    rot = exch.post(f"{API}/auth/refresh")
    assert rot.status_code == 200, rot.text
    rot_body = rot.json()
    assert rot_body.get("access_token")
    assert "refresh_token" not in rot_body
    # New opaque refresh token should have replaced the old one in the jar.
    new_raw = exch.cookies.get(REFRESH_COOKIE)
    assert new_raw and new_raw != raw_refresh, \
        "atomic family rotation must replace the refresh cookie value"


def test_oauth_exchange_handoff_is_single_use():
    s, user, access = _register_client()
    raw_refresh = s.cookies.get(REFRESH_COOKIE)
    handoff_id = _seed_handoff(user["id"], access, raw_refresh)

    r1 = requests.post(f"{API}/auth/google/oauth/exchange",
                       json={"handoff_id": handoff_id})
    assert r1.status_code == 200, r1.text

    r2 = requests.post(f"{API}/auth/google/oauth/exchange",
                       json={"handoff_id": handoff_id})
    assert r2.status_code == 404, r2.text


def test_oauth_exchange_handoff_expires_after_5_min():
    s, user, access = _register_client()
    raw_refresh = s.cookies.get(REFRESH_COOKIE)
    # Seed a handoff whose `created_at` is 6 minutes in the past.
    handoff_id = _seed_handoff(user["id"], access, raw_refresh, age_seconds=360)

    r = requests.post(f"{API}/auth/google/oauth/exchange",
                      json={"handoff_id": handoff_id})
    assert r.status_code == 410, r.text


def test_oauth_exchange_missing_handoff_id_400():
    r = requests.post(f"{API}/auth/google/oauth/exchange", json={})
    assert r.status_code == 400


def test_oauth_exchange_unknown_handoff_404():
    r = requests.post(f"{API}/auth/google/oauth/exchange",
                      json={"handoff_id": "does-not-exist"})
    assert r.status_code == 404


def test_oauth_exchange_inactive_user_denied():
    s, user, access = _register_client()
    raw_refresh = s.cookies.get(REFRESH_COOKIE)
    _db().users.update_one({"id": user["id"]}, {"$set": {"is_active": False}})
    handoff_id = _seed_handoff(user["id"], access, raw_refresh)
    r = requests.post(f"{API}/auth/google/oauth/exchange",
                      json={"handoff_id": handoff_id})
    assert r.status_code == 403


def test_oauth_authorize_returns_503_when_google_not_configured():
    """When GOOGLE_OAUTH_* env vars are absent, authorize is a graceful 503."""
    if os.environ.get("GOOGLE_OAUTH_CLIENT_ID") and \
       os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") and \
       os.environ.get("GOOGLE_OAUTH_REDIRECT_URI"):
        pytest.skip("Google OAuth is configured in this env; behaviour tested elsewhere")
    r = requests.get(f"{API}/auth/google/oauth/authorize")
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# Regression — password login + refresh still work                             #
# --------------------------------------------------------------------------- #
def test_password_login_and_refresh_unaffected():
    """Ensure Sprint 2 password path is not regressed by exchange refactor."""
    s = requests.Session()
    email = f"pwreg_{uuid.uuid4().hex[:10]}@example.com"
    password = "Sprint2Test!23456"
    r = s.post(f"{API}/auth/register", json={
        "email": email, "password": password,
        "full_name": "Password Regression", "phone": "+15555550101",
    })
    assert r.status_code == 200, r.text
    access = r.json()["access_token"]
    assert access
    assert s.cookies.get(REFRESH_COOKIE)

    rr = s.post(f"{API}/auth/refresh")
    assert rr.status_code == 200, rr.text
    body = rr.json()
    assert body.get("access_token")
    assert "refresh_token" not in body


# --------------------------------------------------------------------------- #
# Log hygiene — no PHI / secrets leaked                                        #
# --------------------------------------------------------------------------- #
def test_no_sensitive_data_leaks_into_backend_logs():
    """Trigger the exchange flow, then scan the tail of the backend log for
    obviously sensitive substrings. This is a coarse but valuable smoke check."""
    s, user, access = _register_client()
    raw_refresh = s.cookies.get(REFRESH_COOKIE)
    handoff_id = _seed_handoff(user["id"], access, raw_refresh)
    r = requests.post(f"{API}/auth/google/oauth/exchange",
                      json={"handoff_id": handoff_id})
    assert r.status_code == 200

    # Read last ~4000 lines of every rotated supervisor backend log.
    import glob
    tail_bytes = []
    for path in sorted(glob.glob("/var/log/supervisor/backend.*.log")):
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 200_000))
                tail_bytes.append(f.read())
        except OSError:
            continue
    tail = b"\n".join(tail_bytes).decode("utf-8", errors="ignore")

    # Access token / refresh cookie value / user email must not appear.
    assert access not in tail, "access token must not be logged"
    assert raw_refresh not in tail, "opaque refresh token must not be logged"
    assert user["email"] not in tail, "user email must not appear in logs"
