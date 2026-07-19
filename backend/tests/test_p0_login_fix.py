"""
P0 login fix verification (iter20 targeted test).

Verifies the fix for the audit._CHAIN_LOCK deadlock (threading.Lock -> asyncio.Lock).
Root cause: /api/auth/login and every other /api call hung because a threading
lock was held across `await db.audit_logs.insert_one(...)`, freezing the event
loop when two coroutines contended. Cloudflare then returned 502.

Scope (do NOT expand):
  1. GET  /api/health              < 2s, 200 JSON
  2. POST /api/auth/login (no MFA) 200 + mfa_required=true
  3. POST /api/auth/login (+TOTP)  200 + JWT + Set-Cookie nms_rt
  4. POST /api/auth/refresh        200 + rotated nms_rt, no refresh_token in body
  5. GET  /api/auth/google/oauth/authorize -> 503 "Direct Google OAuth not configured"
  6. Concurrency: 10 parallel bad-login attempts finish <5s each, no hangs.
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import time

import pyotp
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASSWORD = "Admin!2345"
ADMIN_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


# --- 1. Health -------------------------------------------------------------


def test_health_returns_200_fast():
    t0 = time.time()
    r = requests.get(f"{BASE_URL}/api/health", timeout=5)
    elapsed = time.time() - t0
    assert r.status_code == 200, f"health non-200: {r.status_code} {r.text[:200]}"
    assert elapsed < 2.0, f"health too slow: {elapsed:.2f}s"
    body = r.json()
    assert isinstance(body, dict), f"expected JSON dict, got {type(body)}"


# --- 2. Login step-1 (no MFA token) ---------------------------------------


def test_login_without_mfa_returns_mfa_required():
    # NOTE: /app/backend/tests/conftest.py monkey-patches requests.post to
    # auto-append TOTP for seeded workforce accounts. Use requests.request()
    # to bypass the patch and exercise the real MFA-step behavior.
    r = requests.request(
        "POST",
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert body.get("mfa_required") is True, f"mfa_required must be true, got {body}"
    # Access token should be empty string when MFA is still required
    assert body.get("access_token", "") == "", (
        f"access_token must be empty on MFA step, got: {body.get('access_token')!r}"
    )
    assert "user" in body and isinstance(body["user"], dict), "user object missing"
    assert body["user"].get("email") == ADMIN_EMAIL


# --- 3. Login step-2 (with TOTP) ------------------------------------------


def _login_with_totp():
    totp = pyotp.TOTP(ADMIN_TOTP_SECRET).now()
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "mfa_token": totp},
        timeout=10,
    )
    return r


def test_login_with_totp_returns_jwt_and_sets_refresh_cookie():
    r = _login_with_totp()
    assert r.status_code == 200, f"login+TOTP failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    assert body.get("mfa_required") is False, "mfa_required must be false after TOTP"
    access = body.get("access_token") or ""
    assert access and access.count(".") == 2, (
        f"access_token must be a non-empty JWT, got: {access!r}"
    )
    # Set-Cookie header check for nms_rt
    # requests may lower-case or combine — use raw headers
    set_cookie_hdrs = r.headers.get("Set-Cookie", "") or ""
    # multi-value join in requests: use raw list via r.raw.headers if needed
    raw_list = []
    try:
        raw_list = r.raw.headers.getlist("Set-Cookie")  # type: ignore[attr-defined]
    except Exception:
        raw_list = [set_cookie_hdrs]
    joined = " || ".join(raw_list) if raw_list else set_cookie_hdrs
    assert "nms_rt=" in joined, f"nms_rt cookie missing from Set-Cookie: {joined!r}"
    assert "HttpOnly" in joined, f"nms_rt must be HttpOnly: {joined!r}"
    assert "Path=/api/auth/refresh" in joined, (
        f"nms_rt must scope Path=/api/auth/refresh: {joined!r}"
    )
    # SameSite=lax (case-insensitive)
    assert "samesite=lax" in joined.lower(), f"nms_rt must be SameSite=Lax: {joined!r}"
    # requests should also have parsed the cookie into the session
    assert "nms_rt" in r.cookies, "nms_rt not present in response cookies jar"


# --- 4. Refresh (family rotation) -----------------------------------------


def test_refresh_returns_new_access_and_rotates_cookie():
    # Do a fresh login to get a fresh nms_rt cookie
    login = _login_with_totp()
    assert login.status_code == 200, f"prereq login failed: {login.status_code}"
    old_cookie = login.cookies.get("nms_rt")
    assert old_cookie, "no nms_rt in login response"

    r = requests.post(
        f"{BASE_URL}/api/auth/refresh",
        cookies={"nms_rt": old_cookie},
        timeout=10,
    )
    assert r.status_code == 200, f"refresh failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    new_access = body.get("access_token") or ""
    assert new_access and new_access.count(".") == 2, (
        f"refresh must return a JWT access_token, got: {new_access!r}"
    )
    assert "refresh_token" not in body, (
        f"refresh_token MUST NOT appear in JSON body, got keys: {list(body.keys())}"
    )
    # Rotated cookie in Set-Cookie
    try:
        raw_list = r.raw.headers.getlist("Set-Cookie")  # type: ignore[attr-defined]
    except Exception:
        raw_list = [r.headers.get("Set-Cookie", "")]
    joined = " || ".join(raw_list)
    assert "nms_rt=" in joined, f"rotated nms_rt cookie missing: {joined!r}"
    new_cookie = r.cookies.get("nms_rt")
    assert new_cookie, "no new nms_rt cookie in refresh response"
    assert new_cookie != old_cookie, (
        "refresh MUST rotate nms_rt (family rotation) — got same value"
    )


# --- 5. Direct Google OAuth authorize -> 503 by design --------------------


def test_google_oauth_authorize_returns_503_by_design():
    r = requests.get(
        f"{BASE_URL}/api/auth/google/oauth/authorize",
        timeout=10,
        allow_redirects=False,
    )
    assert r.status_code == 503, (
        f"expected 503 (direct OAuth not configured), got {r.status_code}: {r.text[:300]}"
    )
    try:
        body = r.json()
    except Exception:
        body = {}
    detail = (body.get("detail") or "").lower()
    assert "google" in detail and ("not configured" in detail or "configured" in detail), (
        f"detail body should mention Google not configured, got: {body}"
    )


# --- 6. Concurrency deadlock regression -----------------------------------


def _bad_login_call(i: int):
    t0 = time.time()
    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={
                "email": f"nobody+{i}@invalid.local",
                "password": "definitely-wrong-password",
            },
            timeout=5,
        )
        return {"i": i, "status": r.status_code, "elapsed": time.time() - t0}
    except Exception as e:  # noqa: BLE001
        return {"i": i, "status": None, "elapsed": time.time() - t0, "error": str(e)}


def test_10_parallel_bad_logins_do_not_hang():
    """Regression: pre-fix this would deadlock the event loop and every request
    would time out at Cloudflare with 502. Post-fix each should return 401 or
    429 within 5s (well under the timeout)."""
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_bad_login_call, i) for i in range(10)]
        results = [f.result() for f in cf.as_completed(futures, timeout=15)]

    for res in results:
        assert res.get("status") in (401, 429), (
            f"login concurrency: got status={res.get('status')} (expected 401/429). "
            f"details={res}"
        )
        assert res["elapsed"] < 5.0, (
            f"login concurrency: request {res['i']} took {res['elapsed']:.2f}s "
            f"(deadlock symptom). full={res}"
        )
    # Also verify none errored out (timeout etc.)
    errored = [r for r in results if r.get("status") is None]
    assert not errored, f"some login calls failed to complete: {errored}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
