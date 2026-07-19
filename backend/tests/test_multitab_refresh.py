"""
Targeted regression: multi-tab (concurrent) refresh does not trigger
false-positive reuse detection when tabs share a browser (same UA within
the concurrency grace window).

Scenario
--------
1. Log in as admin. Grab the nms_rt cookie value.
2. Fire N concurrent POST /api/auth/refresh requests, each carrying the
   SAME cookie value and the SAME User-Agent header.
3. Expected outcome:
    - Exactly ONE request returns 200 with a new access_token and rotates
      the cookie.
    - The others return HTTP 409 with `{"detail": "concurrency_retry"}`.
    - The session remains ACTIVE (revoked_at is None).
    - No `auth.refresh_reuse_detected` audit event is emitted (the
      concurrency grace path only writes `auth.refresh_concurrency_detected`).
    - A subsequent refresh using the winning cookie succeeds (family
      is intact).
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pymongo
import pyotp
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
TOTP = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PW = "Admin!2345"

MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def _db():
    return pymongo.MongoClient(MONGO)[DB_NAME]


def _login() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update({"User-Agent": "MultiTabTest/1.0"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("mfa_required"):
        r = s.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PW,
            "mfa_token": pyotp.TOTP(TOTP).now()})
        assert r.status_code == 200
        body = r.json()
    rt = s.cookies.get("nms_rt")
    assert rt, "login must set nms_rt cookie"
    return s, rt


def _refresh_with(cookie_value: str) -> tuple[int, dict | None]:
    """Fire a single refresh with the given nms_rt cookie value and a
    consistent UA so the backend treats us as a same-browser tab."""
    r = requests.post(
        f"{API}/auth/refresh",
        cookies={"nms_rt": cookie_value},
        headers={"User-Agent": "MultiTabTest/1.0"},
        timeout=15,
    )
    try:
        body = r.json()
    except Exception:
        body = None
    return r.status_code, body, r.cookies.get("nms_rt")


def test_three_tabs_concurrent_refresh_returns_one_200_and_others_409():
    _, rt = _login()

    # Snapshot audit-log high-water mark to detect any new
    # `auth.refresh_reuse_detected` rows created by the concurrent burst.
    reuse_before = _db().audit_logs.count_documents({
        "action": "auth.refresh_reuse_detected",
    })

    # Fire 3 concurrent refresh calls with the SAME cookie value.
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(_refresh_with, rt) for _ in range(3)]
        results = [f.result() for f in futures]

    statuses = sorted([r[0] for r in results])
    ok_results = [r for r in results if r[0] == 200]
    concurrency_results = [r for r in results if r[0] == 409]

    # -- exactly one 200 + rest are 409 concurrency_retry -------------------
    assert len(ok_results) == 1, \
        f"expected exactly one 200 refresh; got statuses={statuses}"
    assert len(concurrency_results) == len(results) - 1, \
        f"expected {len(results)-1} 409s; got {statuses}"
    for status, body, _cookie in concurrency_results:
        assert body and body.get("detail") == "concurrency_retry", \
            f"409 body must be concurrency_retry; got {body!r}"

    # -- session must remain active -----------------------------------------
    # No new refresh_reuse_detected rows for this session.
    reuse_after = _db().audit_logs.count_documents({
        "action": "auth.refresh_reuse_detected",
    })
    assert reuse_after == reuse_before, \
        f"multi-tab burst produced {reuse_after - reuse_before} spurious refresh_reuse_detected rows"

    # -- winner's new cookie can still refresh (family intact) --------------
    winner_cookie = ok_results[0][2]
    assert winner_cookie and winner_cookie != rt, \
        "winning refresh must rotate the nms_rt cookie"
    time.sleep(0.4)
    status2, body2, cookie2 = _refresh_with(winner_cookie)
    assert status2 == 200, f"follow-up refresh with winner cookie failed: {status2} {body2}"
    assert cookie2 and cookie2 != winner_cookie


def test_true_reuse_outside_grace_still_burns_family():
    """Sanity check — an out-of-grace reuse still triggers reuse detection
    so the fix does not weaken the security control."""
    _, rt = _login()

    # Rotate once so `rt` becomes a used token.
    status, body, new_cookie = _refresh_with(rt)
    assert status == 200
    time.sleep(0.4)

    # Force the used-at timestamp to WAY outside the grace window (2 minutes ago).
    _db().refresh_tokens.update_many(
        {"used_at": {"$ne": None}, "session_id": {"$exists": True}},
        [{"$set": {
            "used_at": datetime.now(timezone.utc) - timedelta(minutes=2),
        }}],
    )

    # Present the original (now stale) token — must trigger reuse.
    status, body, _ = _refresh_with(rt)
    assert status == 401, f"stale-token reuse must be rejected 401; got {status} {body}"
