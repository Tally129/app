"""
Phase 6 tests for NatMedSol EMR.
Covers:
  - GET /api/reports/eod-cash-drawer (PDF + RBAC)
  - POST /api/clients with extended EHR fields + MRN auto-gen + GET round-trip
  - GET /api/analytics/overview notes_by_provider shape (N+1 -> $in fix)
  - GET /api/visits/{appt_id}/chat (RBAC + empty default + populated after WS chat)
  - POST /api/visits/{appt_id}/recording (multipart upload, RBAC, persistence)
  - WS /api/ws/visit/{appt_id} signaling/auth/RBAC + chat persistence
"""
import os
import re
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


# -------- helpers / fixtures --------
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
    """Register-or-login a deterministic test client."""
    email = "test_client_phase6@example.com"
    pwd = "ClientPass123!"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": pwd, "full_name": "TEST P6 Client", "role": "client"
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
    """Ensure the client has a corresponding /clients entry (self)."""
    me = requests.get(f"{API}/clients/me", headers=client_session["headers"], timeout=15)
    if me.status_code == 200:
        return me.json()
    # Otherwise, create one tied to the user
    r = requests.post(f"{API}/clients", headers=admin_headers, json={
        "user_id": client_session["user_id"],
        "full_name": "TEST P6 Client",
        "email": client_session["email"],
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ---------- 1. EOD Cash Drawer PDF ----------
class TestEodCashDrawer:
    def test_admin_returns_pdf(self, admin_headers):
        r = requests.get(f"{API}/reports/eod-cash-drawer", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        cd = r.headers.get("content-disposition", "")
        today = datetime.now(timezone.utc).date().isoformat()
        assert today in cd, f"filename should contain today's date {today}, got {cd}"
        # PDF magic bytes
        assert r.content[:4] == b"%PDF", "Body is not a valid PDF stream"

    def test_client_forbidden(self, client_session):
        r = requests.get(f"{API}/reports/eod-cash-drawer",
                         headers=client_session["headers"], timeout=20)
        assert r.status_code == 403, r.text

    def test_unauth_rejected(self):
        r = requests.get(f"{API}/reports/eod-cash-drawer", timeout=20)
        assert r.status_code in (401, 403)


# ---------- 2. Clients - extended fields + MRN auto-gen ----------
class TestClientExtendedFields:
    EXT = {
        "full_name": "TEST P6 Patient Full",
        "email": "TEST_p6_patient@example.com",
        "phone": "555-0100",
        "dob": "1990-04-12",
        "sex": "F",
        "pronouns": "she/her",
        "gender_identity": "Female",
        "language": "English",
        "marital_status": "Single",
        "alt_phone": "555-0200",
        "referral_source": "Web",
        "primary_concern": "Fatigue and stress",
        "wellness_goals": "Improve energy",
        "current_supplements": "Magnesium",
        "dietary_restrictions": "Vegetarian",
        "allergies": "Penicillin",
        "comms_pref": "email",
        "consent_telehealth": True,
        "consent_photo": False,
        "consent_marketing": True,
        "notes": "Initial intake from wizard",
    }

    def test_create_with_extended_fields_autogen_mrn(self, admin_headers):
        r = requests.post(f"{API}/clients", headers=admin_headers, json=self.EXT, timeout=15)
        assert r.status_code in (200, 201), r.text
        c = r.json()
        # MRN auto-generated as NMS-{6 hex upper}
        assert c.get("mrn"), "mrn should be auto-generated"
        assert re.match(r"^NMS-[A-F0-9]{6}$", c["mrn"]), f"mrn pattern wrong: {c['mrn']}"
        # Verify extended fields persisted (email is server-lowercased)
        for k, v in self.EXT.items():
            expected = v.lower() if k == "email" and isinstance(v, str) else v
            assert c.get(k) == expected, f"field mismatch for {k}: {c.get(k)} != {expected}"

        # GET round-trip
        cid = c["id"]
        g = requests.get(f"{API}/clients/{cid}", headers=admin_headers, timeout=15)
        assert g.status_code == 200, g.text
        gc = g.json()
        assert gc["mrn"] == c["mrn"]
        assert gc["primary_concern"] == self.EXT["primary_concern"]
        assert gc["consent_telehealth"] is True
        assert gc["allergies"] == self.EXT["allergies"]

    def test_explicit_mrn_preserved(self, admin_headers):
        payload = {**self.EXT, "email": "TEST_p6_explicit_mrn@example.com",
                   "full_name": "TEST P6 Explicit MRN", "mrn": "NMS-CUSTOM"}
        r = requests.post(f"{API}/clients", headers=admin_headers, json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text
        assert r.json()["mrn"] == "NMS-CUSTOM"

    def test_list_clients_returns_extended_fields(self, admin_headers):
        r = requests.get(f"{API}/clients", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        # at least one TEST p6 record exists
        ours = [c for c in items if (c.get("email") or "").startswith("test_p6_")]
        assert ours, "expected our TEST p6 client(s) in list"
        sample = ours[0]
        # extended keys present in serialized output
        for k in ["mrn", "primary_concern", "consent_telehealth", "pronouns", "allergies"]:
            assert k in sample, f"client list missing field {k}"


# ---------- 3. Analytics notes_by_provider shape ----------
class TestAnalyticsProviderShape:
    def test_notes_by_provider_resolves_name(self, admin_headers, practitioner_headers):
        r = requests.get(f"{API}/analytics/overview?days=365", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        nbp = data.get("notes_by_provider")
        assert isinstance(nbp, list)
        # Each row must have provider_id, provider_name, notes (count)
        for row in nbp:
            assert "provider_id" in row
            assert "provider_name" in row
            assert "notes" in row
            assert isinstance(row["notes"], int)


# ---------- 4. Appointment + Visit chat + recording ----------
@pytest.fixture(scope="session")
def telehealth_appt(admin_headers, practitioner_token, client_self):
    """Create a telehealth appointment for the test client."""
    # Resolve practitioner id
    me = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {practitioner_token}"}, timeout=15)
    assert me.status_code == 200, me.text
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
        "notes": "TEST p6 telehealth",
        "consent_telehealth": True,
    }
    r = requests.post(f"{API}/appointments", headers=admin_headers, json=payload, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


class TestVisitChat:
    def test_chat_history_empty_for_new(self, telehealth_appt, admin_headers):
        appt_id = telehealth_appt["id"]
        r = requests.get(f"{API}/visits/{appt_id}/chat", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_chat_history_404_for_unknown(self, admin_headers):
        r = requests.get(f"{API}/visits/no-such-appt/chat",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 404

    def test_client_cannot_read_other_visit(self, telehealth_appt, client_session, admin_headers):
        # Create a 2nd appt belonging to a different (admin-created) client
        # Use admin to create a fresh client and appointment
        c = requests.post(f"{API}/clients", headers=admin_headers, json={
            "full_name": "TEST P6 Other Client",
            "email": "TEST_p6_other@example.com",
        }, timeout=15)
        assert c.status_code in (200, 201), c.text
        other_cid = c.json()["id"]

        me = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15).json()
        start = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
        end = start + timedelta(minutes=30)
        a = requests.post(f"{API}/appointments", headers=admin_headers, json={
            "client_id": other_cid,
            "practitioner_id": me["id"],
            "visit_mode": "telehealth",
            "start": start.isoformat(), "end": end.isoformat(),
            "status": "confirmed",
            "consent_telehealth": True,
        }, timeout=15)
        assert a.status_code in (200, 201), a.text
        other_appt_id = a.json()["id"]

        r = requests.get(f"{API}/visits/{other_appt_id}/chat",
                         headers=client_session["headers"], timeout=15)
        assert r.status_code == 403, r.text


class TestRecordingUpload:
    def test_practitioner_uploads(self, telehealth_appt, practitioner_headers):
        appt_id = telehealth_appt["id"]
        files = {"file": ("test.webm", b"\x1a\x45\xdf\xa3FAKEWEBM", "video/webm")}
        r = requests.post(f"{API}/visits/{appt_id}/recording",
                          headers=practitioner_headers, files=files, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "file_id" in body and isinstance(body["file_id"], str)
        assert body.get("size", 0) > 0

    def test_client_forbidden(self, telehealth_appt, client_session):
        appt_id = telehealth_appt["id"]
        files = {"file": ("test.webm", b"data", "video/webm")}
        r = requests.post(f"{API}/visits/{appt_id}/recording",
                          headers=client_session["headers"], files=files, timeout=30)
        assert r.status_code == 403

    def test_404_for_unknown(self, practitioner_headers):
        files = {"file": ("test.webm", b"data", "video/webm")}
        r = requests.post(f"{API}/visits/no-such-appt/recording",
                          headers=practitioner_headers, files=files, timeout=30)
        assert r.status_code == 404


# ---------- 5. WebSocket signaling ----------
def _ws_url(appt_id, token):
    return f"{WS_API}/ws/visit/{appt_id}?token={token}"


@pytest.mark.asyncio
async def test_ws_invalid_token_rejected(telehealth_appt):
    appt_id = telehealth_appt["id"]
    url = _ws_url(appt_id, "this-is-a-bogus-token")
    try:
        async with websockets.connect(url) as ws:
            await ws.recv()
            pytest.fail("connection should have been rejected")
    except websockets.exceptions.InvalidStatus as e:
        # HTTP-level rejection during handshake (server returns 4xx)
        assert e.response.status_code in (401, 403, 404)
    except websockets.exceptions.ConnectionClosed as e:
        assert e.code == 4401


@pytest.mark.asyncio
async def test_ws_missing_appointment(admin_token):
    url = _ws_url("no-such-appt-xyz", admin_token)
    try:
        async with websockets.connect(url) as ws:
            await ws.recv()
            pytest.fail("connection should have been rejected with 4404")
    except websockets.exceptions.ConnectionClosed as e:
        assert e.code == 4404
    except websockets.exceptions.InvalidStatus as e:
        assert e.response.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_ws_provider_join_and_chat_persists(telehealth_appt, admin_token,
                                                  admin_headers):
    appt_id = telehealth_appt["id"]
    url = _ws_url(appt_id, admin_token)
    async with websockets.connect(url) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert msg["type"] == "joined"
        assert msg["role"] == "provider"
        assert "peer_present" in msg
        # Send chat -> persists to db.visit_chat (relay to peer is ok if absent)
        await ws.send(json.dumps({"type": "chat",
                                  "body": "TEST P6 ws chat hello"}))
        # Tiny wait to allow async persistence
        await asyncio.sleep(0.6)

    # Verify persistence via REST
    r = requests.get(f"{API}/visits/{appt_id}/chat", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    bodies = [m.get("body") for m in r.json()]
    assert "TEST P6 ws chat hello" in bodies, f"chat not persisted, got: {bodies}"


@pytest.mark.asyncio
async def test_ws_client_wrong_appt_rejected(telehealth_appt, client_session, admin_headers):
    """A client connecting to an appointment that isn't theirs should be rejected with 4403."""
    # Make an appointment that belongs to a *different* client
    c = requests.post(f"{API}/clients", headers=admin_headers, json={
        "full_name": "TEST P6 Other WS Client",
        "email": "TEST_p6_ws_other@example.com",
    }, timeout=15).json()
    me = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15).json()
    start = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0)
    end = start + timedelta(minutes=30)
    a = requests.post(f"{API}/appointments", headers=admin_headers, json={
        "client_id": c["id"],
        "practitioner_id": me["id"],
        "visit_mode": "telehealth",
        "start": start.isoformat(), "end": end.isoformat(),
        "status": "confirmed",
        "consent_telehealth": True,
    }, timeout=15).json()
    other_appt_id = a["id"]

    url = _ws_url(other_appt_id, client_session["token"])
    try:
        async with websockets.connect(url) as ws:
            await ws.recv()
            pytest.fail("client should have been rejected (4403)")
    except websockets.exceptions.ConnectionClosed as e:
        assert e.code == 4403
    except websockets.exceptions.InvalidStatus as e:
        assert e.response.status_code in (401, 403, 404)
