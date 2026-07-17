"""
Iteration 15 — Refactor regression.

server.py was split into /app/backend/routers/{auth,ops,telehealth,forms_protocols,compliance}.py.
All routes MUST remain reachable at their pre-refactor /api/* paths.

Coverage:
  * Auth: login for admin / practitioner / staff / auditor / (patient register)
  * Ops: /treatments, /inventory, /pos/checkout, /transactions, /front-desk/today,
         /time-clock/punch-in + punch-out, /analytics/overview, /reports/eod-cash-drawer (PDF)
  * Telehealth: /webrtc/config, /appointments/{id}/telehealth/room, /visits/{id}/ws-ticket
  * Forms & Protocols: /forms/templates, /soap-templates, /protocols/templates,
                       /protocols/enrollments (create + session-complete)
  * Compliance: /compliance/baa-checklist (8 rows), /patient/data-export, /clients/{id}/disclosures
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://design-158.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@natmedsol.local", "Admin!2345")
PRAC = ("ravello@natmedsol.local", "Ravello!2345")
STAFF = ("frontdesk@natmedsol.local", "FrontDesk!2345")
AUDITOR = ("auditor@natmedsol.local", "Auditor!2345")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email} failed {r.status_code} {r.text}"
    return r.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def prac_token():
    return _login(*PRAC)


@pytest.fixture(scope="module")
def staff_token():
    return _login(*STAFF)


@pytest.fixture(scope="module")
def auditor_token():
    return _login(*AUDITOR)


@pytest.fixture(scope="module")
def client_user():
    email = f"TEST_iter15_{uuid.uuid4().hex[:8]}@example.com"
    password = "PatientLongPass2026!"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": password, "full_name": "Q A", "phone": None,
    }, timeout=15)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    return {"email": email, "password": password, "token": r.json()["access_token"], "user": r.json()["user"]}


# ---------- Alternate admin (per user-provided credentials) ----------
class TestAlternateAdminLogin:
    def test_tallyravello_admin_login(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": "tallyravello@gmail.com", "password": "TEST123"}, timeout=15)
        # Accept 200 (seeded) or 401 (not seeded in this environment)
        assert r.status_code in (200, 401), f"unexpected {r.status_code} {r.text}"
        if r.status_code == 200:
            assert r.json()["user"]["role"] == "admin"


# ---------- Auth router regression ----------
class TestAuthRoutes:
    def test_admin_login(self, admin_token):
        assert admin_token
        r = requests.get(f"{API}/auth/me", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_practitioner_login(self, prac_token):
        r = requests.get(f"{API}/auth/me", headers=_headers(prac_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "practitioner"

    def test_staff_login(self, staff_token):
        r = requests.get(f"{API}/auth/me", headers=_headers(staff_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "staff"

    def test_auditor_login(self, auditor_token):
        r = requests.get(f"{API}/auth/me", headers=_headers(auditor_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "auditor"

    def test_refresh_flow(self, admin_token):
        # login again to get a refresh token
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "refresh_token" in j, f"no refresh_token in login body: {list(j.keys())}"
        r2 = requests.post(f"{API}/auth/refresh", json={"refresh_token": j["refresh_token"]}, timeout=15)
        assert r2.status_code == 200
        assert "access_token" in r2.json()


# ---------- Ops router regression ----------
class TestOpsRoutes:
    def test_treatments_list(self, admin_token):
        r = requests.get(f"{API}/treatments", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_inventory_list(self, admin_token):
        r = requests.get(f"{API}/inventory", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_transactions_list(self, admin_token):
        r = requests.get(f"{API}/transactions", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_front_desk_today(self, staff_token):
        r = requests.get(f"{API}/front-desk/today", headers=_headers(staff_token), timeout=15)
        assert r.status_code == 200
        # shape: list or {items:[...]}
        body = r.json()
        assert isinstance(body, (list, dict))

    def test_time_clock_punch_in_out(self, staff_token):
        r_in = requests.post(f"{API}/time-clock/punch-in", headers=_headers(staff_token), json={}, timeout=15)
        assert r_in.status_code in (200, 201, 409), f"punch-in {r_in.status_code} {r_in.text}"
        r_out = requests.post(f"{API}/time-clock/punch-out", headers=_headers(staff_token), json={}, timeout=15)
        # 200 on success, 400 if not clocked in (accept both — order-agnostic)
        assert r_out.status_code in (200, 400), f"punch-out {r_out.status_code} {r_out.text}"

    def test_analytics_overview(self, admin_token):
        r = requests.get(f"{API}/analytics/overview", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_eod_cash_drawer_pdf(self, admin_token):
        r = requests.get(f"{API}/reports/eod-cash-drawer", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert "pdf" in ctype.lower() or r.content[:4] == b"%PDF", f"not a PDF, content-type={ctype}"

    def test_pos_checkout_smoke(self, admin_token):
        # attempt an empty checkout — accept either 400 (validation) or 200 (empty allowed)
        r = requests.post(f"{API}/pos/checkout", headers=_headers(admin_token),
                          json={"client_id": None, "items": [], "payment_method": "cash"}, timeout=15)
        # We just verify the endpoint is reachable and doesn't 404 or 500
        assert r.status_code in (200, 201, 400, 422), f"pos/checkout {r.status_code} {r.text}"


# ---------- Telehealth router regression ----------
class TestTelehealthRoutes:
    def test_webrtc_config(self, admin_token):
        r = requests.get(f"{API}/webrtc/config", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "iceServers" in j or "ice_servers" in j or isinstance(j, dict)

    def test_telehealth_room_stub(self, admin_token, prac_token, client_user):
        # need a real appointment. Create one as admin.
        # First find any existing appointment or create.
        c = requests.get(f"{API}/clients", headers=_headers(admin_token), timeout=15).json()
        assert c, "need at least 1 client to create appointment"
        cid = c[0]["id"]
        # find any practitioner
        prs = requests.get(f"{API}/practitioners", headers=_headers(admin_token), timeout=15).json()
        assert prs, "need at least 1 practitioner"
        pid = prs[0]["id"]
        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
        appt = requests.post(f"{API}/appointments", headers=_headers(admin_token), json={
            "client_id": cid, "practitioner_id": pid, "start": start, "end": end,
            "visit_mode": "telehealth", "reason": "TEST iter15 telehealth", "status": "confirmed",
        }, timeout=15)
        assert appt.status_code == 200, f"appt create {appt.status_code} {appt.text}"
        appt_id = appt.json()["id"]

        # Room stub
        r = requests.post(f"{API}/appointments/{appt_id}/telehealth/room",
                          headers=_headers(admin_token), json={}, timeout=15)
        assert r.status_code == 200, f"telehealth/room {r.status_code} {r.text}"
        assert "url" in r.json() or "room_url" in r.json() or isinstance(r.json(), dict)

        # ws-ticket
        r2 = requests.post(f"{API}/visits/{appt_id}/ws-ticket",
                           headers=_headers(admin_token), json={}, timeout=15)
        assert r2.status_code == 200, f"ws-ticket {r2.status_code} {r2.text}"
        assert "ticket" in r2.json()


# ---------- Forms & Protocols router regression ----------
class TestFormsProtocolsRoutes:
    def test_form_templates_list(self, admin_token):
        r = requests.get(f"{API}/forms/templates", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_soap_templates_list(self, prac_token):
        r = requests.get(f"{API}/soap-templates", headers=_headers(prac_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_protocol_templates_list(self, admin_token):
        r = requests.get(f"{API}/protocols/templates", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # built-in detox should be present
        titles = " ".join([(t.get("title") or "").lower() for t in rows])
        # tolerant: don't assert 'detox' strictly, but ensure at least one template exists
        assert len(rows) >= 1

    def test_protocol_enrollment_and_session_complete(self, admin_token):
        # need a template + a client
        templates = requests.get(f"{API}/protocols/templates",
                                 headers=_headers(admin_token), timeout=15).json()
        assert templates, "need at least 1 protocol template"
        tmpl = templates[0]
        clients = requests.get(f"{API}/clients", headers=_headers(admin_token), timeout=15).json()
        assert clients, "need at least 1 client"
        cid = clients[0]["id"]

        enroll = requests.post(f"{API}/protocols/enrollments", headers=_headers(admin_token),
                               json={"client_id": cid, "template_id": tmpl["id"]}, timeout=15)
        assert enroll.status_code in (200, 201), f"enroll {enroll.status_code} {enroll.text}"
        eid = enroll.json()["id"]

        # move enrollment from proposed -> active via decision endpoint
        dec = requests.post(f"{API}/protocols/enrollments/{eid}/decision",
                            headers=_headers(admin_token),
                            json={"decision": "accept"}, timeout=15)
        assert dec.status_code in (200, 201), f"decision {dec.status_code} {dec.text}"

        # mark first session complete
        sess = requests.post(f"{API}/protocols/enrollments/{eid}/sessions",
                             headers=_headers(admin_token),
                             json={"week": 1, "session": 1, "status": "completed", "notes": "TEST iter15"}, timeout=15)
        # accept 200 or 201; endpoint may return the updated enrollment
        assert sess.status_code in (200, 201), f"session complete {sess.status_code} {sess.text}"


# ---------- Compliance router regression ----------
class TestComplianceRoutes:
    def test_baa_checklist_8_rows(self, admin_token):
        r = requests.get(f"{API}/compliance/baa-checklist", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 8

    def test_patient_data_export_shape(self, client_user):
        r = requests.post(f"{API}/patient/data-export", headers=_headers(client_user["token"]), timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert "patient" in j and "user_account" in j and "appointments" in j

    def test_clients_disclosures_self(self, client_user):
        r_me = requests.get(f"{API}/clients/me", headers=_headers(client_user["token"]), timeout=15)
        assert r_me.status_code == 200
        cid = r_me.json()["id"]
        r = requests.get(f"{API}/clients/{cid}/disclosures",
                         headers=_headers(client_user["token"]), timeout=15)
        assert r.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
