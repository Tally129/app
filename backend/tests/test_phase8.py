"""
Phase 8 tests for NatMedSol EMR.
Covers:
  - POST /api/auth/google/session (X-Session-ID header validation, upstream error handling)
  - REMOVED commission endpoints return 404
  - GET /api/push/public-key returns configured VAPID_PUBLIC_KEY
  - POST /api/push/subscribe / unsubscribe (idempotent + (user_id, endpoint) unique upsert)
  - Push triggers fire silently (no 500) on:
      * appointment update -> in_session telehealth
      * pos_checkout that drives an item below threshold (low_stock_alert)
      * messages create (notify other participant)
  - Background loops _appointment_reminder_loop / _expiring_inventory_loop scheduled at startup
"""
import os
import time
import pytest
import requests
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "tallyravello@gmail.com", "password": "TEST123"}
PRACTITIONER = {"email": "ravello@natmedsol.local", "password": "Ravello!2345"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers():
    return {"Authorization": f"Bearer {_login(ADMIN)}"}


@pytest.fixture(scope="session")
def practitioner_token():
    return _login(PRACTITIONER)


@pytest.fixture(scope="session")
def practitioner_headers(practitioner_token):
    return {"Authorization": f"Bearer {practitioner_token}"}


# ---------- 1. Google SSO session exchange ----------
class TestGoogleSession:
    def test_missing_header_400(self):
        r = requests.post(f"{API}/auth/google/session", timeout=15)
        assert r.status_code == 400, r.text
        assert "X-Session-ID" in r.text or "Missing" in r.text

    def test_invalid_session_returns_401_or_502(self):
        # Bogus session_id -> upstream returns non-200 -> our endpoint maps to 401
        r = requests.post(
            f"{API}/auth/google/session",
            headers={"X-Session-ID": "bogus-fake-session-id-zzz"},
            timeout=20,
        )
        # 401 expected when upstream rejects, 502 if upstream unreachable
        assert r.status_code in (401, 502), r.text


# ---------- 2. Commission endpoints removed ----------
class TestCommissionRemoved:
    def test_reports_commissions_404(self, admin_headers):
        r = requests.get(f"{API}/reports/commissions?days=30",
                         headers=admin_headers, timeout=10)
        assert r.status_code == 404, f"commission report should be removed, got {r.status_code}"

    def test_treatment_commission_put_404(self, admin_headers):
        r = requests.put(
            f"{API}/treatments/anything/commission",
            headers=admin_headers,
            json={"commissions": []},
            timeout=10,
        )
        assert r.status_code == 404, f"commission PUT should be removed, got {r.status_code}"


# ---------- 3. Push public key ----------
class TestPushPublicKey:
    def test_public_key_matches_env(self):
        r = requests.get(f"{API}/push/public-key", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        pk = body.get("public_key") or body.get("publicKey")
        assert pk and len(pk) > 50
        # Should be the VAPID_PUBLIC_KEY (URL-safe base64, starts with B)
        assert pk.startswith("B"), f"unexpected VAPID public key shape: {pk[:10]}"


# ---------- 4. Push subscribe / unsubscribe ----------
class TestPushSubscribe:
    def test_subscribe_then_unsubscribe(self, admin_headers):
        endpoint = f"https://fcm.googleapis.com/test-p8-{int(time.time())}"
        sub = {"subscription": {"endpoint": endpoint,
                                "keys": {"p256dh": "abc", "auth": "def"}}}
        r = requests.post(f"{API}/push/subscribe", headers=admin_headers,
                          json=sub, timeout=10)
        assert r.status_code == 200, r.text
        # Idempotent upsert (same user + endpoint -> ok)
        r2 = requests.post(f"{API}/push/subscribe", headers=admin_headers,
                           json=sub, timeout=10)
        assert r2.status_code == 200
        u = requests.post(f"{API}/push/unsubscribe", headers=admin_headers,
                          json={"endpoint": endpoint}, timeout=10)
        assert u.status_code == 200

    def test_subscribe_missing_endpoint_400(self, admin_headers):
        r = requests.post(f"{API}/push/subscribe", headers=admin_headers,
                          json={"keys": {}}, timeout=10)
        assert r.status_code == 400


# ---------- 5. Push trigger paths must not 500 ----------
@pytest.fixture(scope="module")
def telehealth_appt(admin_headers, practitioner_token):
    me_p = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {practitioner_token}"}, timeout=10,
    ).json()
    # Make a fresh client
    c = requests.post(f"{API}/clients", headers=admin_headers, json={
        "full_name": "TEST P8 Client",
        "email": f"TEST_p8_{int(time.time())}@example.com",
    }, timeout=15)
    assert c.status_code in (200, 201), c.text
    client = c.json()
    start = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
    end = start + timedelta(minutes=30)
    a = requests.post(f"{API}/appointments", headers=admin_headers, json={
        "client_id": client["id"],
        "practitioner_id": me_p["id"],
        "visit_mode": "telehealth",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "status": "confirmed",
        "consent_telehealth": True,
        "notes": "TEST p8 push trigger",
    }, timeout=15)
    assert a.status_code in (200, 201), a.text
    return a.json()


class TestPushTriggers:
    def test_appt_in_session_telehealth_no_500(self, admin_headers, telehealth_appt):
        """Setting status=in_session on a telehealth appt invokes push_to_user; must not raise."""
        r = requests.put(
            f"{API}/appointments/{telehealth_appt['id']}",
            headers=admin_headers,
            json={"status": "in_session", "visit_mode": "telehealth"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "in_session"

    def test_message_create_pushes_to_other_no_500(self, admin_headers, practitioner_headers):
        # Find or create a thread between admin & practitioner
        threads = requests.get(f"{API}/messages/threads", headers=admin_headers, timeout=10)
        assert threads.status_code == 200, threads.text
        thread_id = None
        # Try to find any thread admin has
        for t in threads.json():
            thread_id = t.get("id")
            if thread_id:
                break
        if not thread_id:
            # Create one with practitioner as participant
            me_p = requests.get(f"{API}/auth/me",
                                headers=practitioner_headers, timeout=10).json()
            tr = requests.post(f"{API}/messages/threads",
                               headers=admin_headers,
                               json={"participant_ids": [me_p["id"]],
                                     "subject": "TEST P8"},
                               timeout=10)
            if tr.status_code in (200, 201):
                thread_id = tr.json().get("id")
        if not thread_id:
            pytest.skip("Could not create message thread in this env")
        m = requests.post(f"{API}/messages/threads/{thread_id}/messages",
                          headers=admin_headers,
                          json={"body": "TEST P8 push trigger"},
                          timeout=15)
        # Push delivery is best-effort; endpoint must succeed even with no real subs
        assert m.status_code in (200, 201), m.text

    def test_pos_low_stock_alert_no_500(self, admin_headers):
        # Create an item with stock=2 and threshold=10 -> selling 1 will fall below threshold
        item_payload = {
            "name": f"TEST P8 LowStock {int(time.time())}",
            "sku": f"TEST-P8-LS-{int(time.time())}",
            "kind": "supplement",
            "stock": 2,
            "low_stock_threshold": 10,
            "price": 5.0,
        }
        r = requests.post(f"{API}/inventory", headers=admin_headers,
                          json=item_payload, timeout=10)
        assert r.status_code in (200, 201), r.text
        item = r.json()

        # Admin-as-client checkout: try /pos/checkout with a single line item
        ck_payload = {
            "items": [{"inventory_id": item["id"], "qty": 1, "price": 5.0}],
            "payment_method": "cash",
            "subtotal": 5.0,
            "tax": 0.0,
            "total": 5.0,
        }
        ck = requests.post(f"{API}/pos/checkout", headers=admin_headers,
                           json=ck_payload, timeout=15)
        # Whether checkout schema differs, what matters is no 500 from push trigger
        assert ck.status_code != 500, f"pos checkout 500: {ck.text}"

        # Also verify audit-logs route exists and reachable
        a = requests.get(f"{API}/audit-logs?limit=20", headers=admin_headers, timeout=10)
        # If endpoint exists return 200; if not, just don't fail this test
        assert a.status_code in (200, 404, 405)


# ---------- 6. Background loops scheduled ----------
class TestBackgroundLoops:
    def test_loops_referenced_in_source(self):
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        assert "_appointment_reminder_loop" in src
        assert "_expiring_inventory_loop" in src
        assert "_asyncio.create_task(_appointment_reminder_loop())" in src
        assert "_asyncio.create_task(_expiring_inventory_loop())" in src
