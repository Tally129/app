"""
Phase 7 tests for NatMedSol EMR.
Covers:
  - POST /api/visits/{id}/ws-ticket (one-shot ticket, RBAC)
  - WS /api/ws/visit/{id}?ticket=... (single-use ticket auth)
  - GET /api/webrtc/config (STUN + optional TURN)
  - PUT/GET /api/visits/{id}/live-soap (provider-only autosave)
  - POST /api/visits/{id}/auto-draft (rule-based SOAP from chat)
  - POST /api/visits/{id}/llm-soap (Claude Sonnet 4.5 via Emergent LLM Key)
  - POST /api/appointments/{id}/recurrence + DELETE series
  - POST /api/inventory/{id}/lots, GET /api/inventory/expiring
  - PUT /api/treatments/{id}/commission, GET /api/reports/commissions
  - /api/push/public-key, subscribe, unsubscribe
"""
import os
import json
import asyncio
import pytest
import requests
from datetime import datetime, timedelta, timezone

import websockets

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
WS_API = f"{WS_BASE}/api"

ADMIN = {"email": "tallyravello@gmail.com", "password": "TEST123"}
PRACTITIONER = {"email": "ravello@natmedsol.local", "password": "Ravello!2345"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="session")
def practitioner_token():
    return _login(PRACTITIONER)


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def practitioner_headers(practitioner_token):
    return {"Authorization": f"Bearer {practitioner_token}"}


@pytest.fixture(scope="session")
def client_session():
    email = "test_client_phase7@example.com"
    pwd = "ClientPass123!"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": pwd, "full_name": "TEST P7 Client", "role": "client"
    }, timeout=15)
    if r.status_code not in (200, 201):
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    return {
        "token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user_id": body["user"]["id"],
        "email": email,
    }


@pytest.fixture(scope="session")
def client_self(client_session, admin_headers):
    me = requests.get(f"{API}/clients/me", headers=client_session["headers"], timeout=15)
    if me.status_code == 200:
        return me.json()
    r = requests.post(f"{API}/clients", headers=admin_headers, json={
        "user_id": client_session["user_id"],
        "full_name": "TEST P7 Client",
        "email": client_session["email"],
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture(scope="session")
def telehealth_appt(admin_headers, practitioner_token, client_self):
    me = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {practitioner_token}"}, timeout=15)
    practitioner_id = me.json()["id"]
    start = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0)
    end = start + timedelta(minutes=30)
    payload = {
        "client_id": client_self["id"],
        "practitioner_id": practitioner_id,
        "visit_mode": "telehealth",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "status": "confirmed",
        "notes": "TEST p7 telehealth",
        "consent_telehealth": True,
    }
    r = requests.post(f"{API}/appointments", headers=admin_headers, json=payload, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ---------- 1. WS one-shot ticket ----------
class TestWsTicket:
    def test_admin_can_issue(self, admin_headers, telehealth_appt):
        r = requests.post(f"{API}/visits/{telehealth_appt['id']}/ws-ticket",
                          headers=admin_headers, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "ticket" in body and len(body["ticket"]) >= 16
        assert body["expires_in"] == 60

    def test_unknown_appt_404(self, admin_headers):
        r = requests.post(f"{API}/visits/no-such-appt/ws-ticket",
                          headers=admin_headers, timeout=10)
        assert r.status_code == 404

    def test_client_can_issue_for_own_appt(self, client_session, telehealth_appt):
        r = requests.post(f"{API}/visits/{telehealth_appt['id']}/ws-ticket",
                          headers=client_session["headers"], timeout=10)
        assert r.status_code == 200, r.text

    def test_client_forbidden_for_others_appt(self, admin_headers, client_session,
                                              practitioner_token):
        # Create an appt for a different client
        c = requests.post(f"{API}/clients", headers=admin_headers, json={
            "full_name": "TEST P7 Other", "email": "TEST_p7_other@example.com",
        }, timeout=15).json()
        me = requests.get(f"{API}/auth/me",
                          headers={"Authorization": f"Bearer {practitioner_token}"}, timeout=15).json()
        start = (datetime.now(timezone.utc) + timedelta(hours=4)).replace(microsecond=0)
        a = requests.post(f"{API}/appointments", headers=admin_headers, json={
            "client_id": c["id"], "practitioner_id": me["id"], "visit_mode": "telehealth",
            "start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat(),
            "status": "confirmed", "consent_telehealth": True,
        }, timeout=15).json()
        r = requests.post(f"{API}/visits/{a['id']}/ws-ticket",
                          headers=client_session["headers"], timeout=10)
        assert r.status_code == 403


# ---------- 2. WS handshake via ticket (single-use) ----------
@pytest.mark.asyncio
async def test_ws_ticket_single_use(admin_headers, telehealth_appt):
    appt_id = telehealth_appt["id"]
    r = requests.post(f"{API}/visits/{appt_id}/ws-ticket",
                      headers=admin_headers, timeout=10)
    ticket = r.json()["ticket"]
    url = f"{WS_API}/ws/visit/{appt_id}?ticket={ticket}"

    # First use: connection accepted, joined event sent
    async with websockets.connect(url) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert msg["type"] == "joined"

    # Second use of same ticket -> rejected with 4401
    try:
        async with websockets.connect(url) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
            pytest.fail("second use of ticket should be rejected")
    except websockets.exceptions.ConnectionClosed as e:
        assert e.code == 4401
    except websockets.exceptions.InvalidStatus as e:
        assert e.response.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_ws_invalid_ticket(telehealth_appt):
    url = f"{WS_API}/ws/visit/{telehealth_appt['id']}?ticket=bogus-ticket-xyz"
    try:
        async with websockets.connect(url) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
            pytest.fail("invalid ticket should be rejected")
    except websockets.exceptions.ConnectionClosed as e:
        assert e.code == 4401
    except websockets.exceptions.InvalidStatus as e:
        assert e.response.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_ws_legacy_token_still_works(admin_token, telehealth_appt):
    """Backward compat: ?token=JWT should still authenticate."""
    url = f"{WS_API}/ws/visit/{telehealth_appt['id']}?token={admin_token}"
    async with websockets.connect(url) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert msg["type"] == "joined"


# ---------- 3. WebRTC config ----------
class TestWebrtcConfig:
    def test_returns_stun(self, admin_headers):
        r = requests.get(f"{API}/webrtc/config", headers=admin_headers, timeout=10)
        assert r.status_code == 200, r.text
        servers = r.json().get("iceServers", [])
        stun = [s for s in servers if str(s.get("urls", "")).startswith("stun:")]
        assert len(stun) >= 2, f"expected >=2 STUN servers, got {servers}"

    def test_turn_included_when_env_set(self, admin_headers):
        r = requests.get(f"{API}/webrtc/config", headers=admin_headers, timeout=10)
        servers = r.json().get("iceServers", [])
        turn_url = os.environ.get("TURN_URL", "")
        if turn_url:
            assert any(turn_url in str(s.get("urls", "")) for s in servers)
        else:
            # In current env TURN is empty -> expect only STUN
            assert all(str(s.get("urls", "")).startswith("stun:") for s in servers)


# ---------- 4. Live SOAP autosave ----------
class TestLiveSoap:
    def test_put_get_round_trip(self, admin_headers, telehealth_appt):
        appt_id = telehealth_appt["id"]
        body = {"subjective": "feels tired", "objective": "alert", "assessment": "stress",
                "plan": "rest + magnesium"}
        r = requests.put(f"{API}/visits/{appt_id}/live-soap",
                         headers=admin_headers, json=body, timeout=10)
        assert r.status_code == 200, r.text
        assert "saved_at" in r.json()
        # Idempotent upsert
        r2 = requests.put(f"{API}/visits/{appt_id}/live-soap",
                          headers=admin_headers, json=body, timeout=10)
        assert r2.status_code == 200
        g = requests.get(f"{API}/visits/{appt_id}/live-soap",
                         headers=admin_headers, timeout=10)
        assert g.status_code == 200, g.text
        d = g.json()
        for k in ("subjective", "objective", "assessment", "plan"):
            assert d.get(k) == body[k]

    def test_client_forbidden(self, client_session, telehealth_appt):
        r = requests.put(f"{API}/visits/{telehealth_appt['id']}/live-soap",
                         headers=client_session["headers"], json={}, timeout=10)
        assert r.status_code == 403


# ---------- 5. Auto-draft (rule-based) ----------
class TestAutoDraft:
    def test_returns_soap_shape(self, admin_headers, telehealth_appt):
        r = requests.post(f"{API}/visits/{telehealth_appt['id']}/auto-draft",
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("subjective", "objective", "assessment", "plan"):
            assert k in d
        assert d.get("source") == "chat_transcript"

    def test_client_forbidden(self, client_session, telehealth_appt):
        r = requests.post(f"{API}/visits/{telehealth_appt['id']}/auto-draft",
                          headers=client_session["headers"], timeout=10)
        assert r.status_code == 403


# ---------- 6. LLM SOAP draft ----------
class TestLlmSoap:
    @pytest.mark.slow
    def test_llm_returns_soap(self, admin_headers, telehealth_appt):
        if not os.environ.get("EMERGENT_LLM_KEY"):
            pytest.skip("EMERGENT_LLM_KEY not set")
        r = requests.post(f"{API}/visits/{telehealth_appt['id']}/llm-soap",
                          headers=admin_headers, timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("source") == "llm"
        assert "claude-sonnet-4-5" in d.get("model", "")
        # At least one section non-empty
        nonempty = sum(1 for k in ("subjective", "objective", "assessment", "plan")
                       if (d.get(k) or "").strip())
        assert nonempty >= 1, f"expected non-empty SOAP fields, got {d}"

    def test_client_forbidden(self, client_session, telehealth_appt):
        r = requests.post(f"{API}/visits/{telehealth_appt['id']}/llm-soap",
                          headers=client_session["headers"], timeout=15)
        assert r.status_code == 403


# ---------- 7. Recurring appointments ----------
class TestRecurrence:
    def test_weekly_creates_4(self, admin_headers, telehealth_appt):
        appt_id = telehealth_appt["id"]
        r = requests.post(f"{API}/appointments/{appt_id}/recurrence",
                          headers=admin_headers,
                          json={"pattern": "weekly", "count": 4}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pattern"] == "weekly"
        assert isinstance(body["created"], list) and len(body["created"]) == 4
        series_id = body["series_id"]
        assert series_id

        # Cancel future series
        d = requests.delete(f"{API}/appointments/series/{series_id}",
                            headers=admin_headers, timeout=15)
        assert d.status_code == 200, d.text
        assert d.json().get("cancelled", 0) >= 4

    def test_unknown_appt_404(self, admin_headers):
        r = requests.post(f"{API}/appointments/no-such-appt/recurrence",
                          headers=admin_headers,
                          json={"pattern": "weekly", "count": 2}, timeout=10)
        assert r.status_code == 404


# ---------- 8. Inventory lots / expiring ----------
@pytest.fixture(scope="class")
def inventory_item(admin_headers):
    payload = {
        "name": "TEST P7 Magnesium",
        "sku": "TEST-P7-MG",
        "kind": "supplement",
        "stock": 0,
        "price": 19.99,
    }
    r = requests.post(f"{API}/inventory", headers=admin_headers, json=payload, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


class TestInventoryLots:
    def test_add_lot_increments_stock(self, admin_headers, inventory_item):
        item_id = inventory_item["id"]
        before = inventory_item.get("stock", 0)
        soon = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        r = requests.post(f"{API}/inventory/{item_id}/lots",
                          headers=admin_headers,
                          json={"lot_number": "LOT-P7-001", "qty": 10,
                                "expires_on": soon, "note": "test lot"},
                          timeout=15)
        assert r.status_code == 200, r.text
        lot = r.json()
        assert lot["lot_number"] == "LOT-P7-001"
        assert lot["qty"] == 10

        # Verify stock updated
        g = requests.get(f"{API}/inventory/{item_id}",
                         headers=admin_headers, timeout=10)
        if g.status_code == 200:
            assert g.json().get("stock") == before + 10
        else:
            # Fallback: list and find
            lst = requests.get(f"{API}/inventory", headers=admin_headers, timeout=10).json()
            it = next((x for x in lst if x.get("id") == item_id), None)
            assert it and it.get("stock") == before + 10

    def test_expiring_includes_item(self, admin_headers, inventory_item):
        r = requests.get(f"{API}/inventory/expiring?days=60",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        items = r.json()
        ids = [i.get("id") for i in items]
        assert inventory_item["id"] in ids

    def test_unknown_item_404(self, admin_headers):
        r = requests.post(f"{API}/inventory/no-such-item/lots",
                          headers=admin_headers,
                          json={"lot_number": "X", "qty": 1}, timeout=10)
        assert r.status_code == 404


# ---------- 9. Commission ----------
# DEPRECATED — commission feature removed in Phase 8 (wellness office is non-commissioned).
# Endpoints PUT /treatments/{id}/commission and GET /reports/commissions now return 404.
class TestCommissionRemoved:
    def test_set_commission_returns_404(self, admin_headers):
        r = requests.put(f"{API}/treatments/anything/commission",
                         headers=admin_headers,
                         json={"commissions": []}, timeout=10)
        assert r.status_code == 404

    def test_report_returns_404(self, admin_headers):
        r = requests.get(f"{API}/reports/commissions?days=30",
                         headers=admin_headers, timeout=10)
        assert r.status_code == 404


# ---------- 10. Push ----------
class TestPush:
    def test_public_key(self):
        r = requests.get(f"{API}/push/public-key", timeout=10)
        assert r.status_code == 200, r.text
        pk = r.json().get("public_key")
        assert pk and len(pk) > 50

    def test_subscribe_and_unsubscribe_nested(self, admin_headers):
        endpoint = "https://fcm.googleapis.com/test-p7-nested-endpoint"
        sub = {"subscription": {"endpoint": endpoint, "keys": {"p256dh": "abc", "auth": "def"}}}
        r = requests.post(f"{API}/push/subscribe", headers=admin_headers, json=sub, timeout=10)
        assert r.status_code == 200, r.text
        # Idempotent (upsert on user_id+endpoint)
        r2 = requests.post(f"{API}/push/subscribe", headers=admin_headers, json=sub, timeout=10)
        assert r2.status_code == 200
        u = requests.post(f"{API}/push/unsubscribe", headers=admin_headers,
                          json={"endpoint": endpoint}, timeout=10)
        assert u.status_code == 200

    def test_subscribe_flat_shape(self, admin_headers):
        endpoint = "https://fcm.googleapis.com/test-p7-flat-endpoint"
        flat = {"endpoint": endpoint, "keys": {"p256dh": "x", "auth": "y"}}
        r = requests.post(f"{API}/push/subscribe", headers=admin_headers, json=flat, timeout=10)
        assert r.status_code == 200, r.text
        u = requests.post(f"{API}/push/unsubscribe", headers=admin_headers,
                          json={"endpoint": endpoint}, timeout=10)
        assert u.status_code == 200

    def test_subscribe_missing_endpoint(self, admin_headers):
        r = requests.post(f"{API}/push/subscribe", headers=admin_headers,
                          json={"keys": {}}, timeout=10)
        assert r.status_code == 400
