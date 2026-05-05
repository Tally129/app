"""
Phase 9 cleanup regression tests for NatMedSol EMR.
Covers iter6 carry-over action items:
  1. Staff user (frontdesk@natmedsol.local / FrontDesk!2345) is seeded and can login.
  2. POST /api/appointments with status='in_session' + visit_mode='telehealth' returns 2xx.
  3. PUT /api/appointments/{id} with {"status":"in_session"} returns 200 and persists.
  4. Regression smoke: GET appointments/clients/inventory/treatments/pos.transactions + login
     for all 4 seeded roles (admin, practitioner, staff, alternate admin).
"""
import os
import pytest
import requests
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "tallyravello@gmail.com", "password": "TEST123"}
PRACTITIONER = {"email": "ravello@natmedsol.local", "password": "Ravello!2345"}
STAFF = {"email": "frontdesk@natmedsol.local", "password": "FrontDesk!2345"}
ALT_ADMIN = {"email": "admin@natmedsol.local", "password": "Admin!2345"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"{creds['email']}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="session")
def admin_headers():
    tok = _login(ADMIN)["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# ---------- 1. Staff user seed ----------
class TestStaffSeed:
    def test_staff_login_works(self):
        data = _login(STAFF)
        assert data["user"]["role"] == "staff"
        assert data["user"]["email"] == STAFF["email"]
        assert data["user"]["is_active"] is True
        assert data["access_token"]

    def test_staff_token_authorizes_basic_endpoints(self):
        tok = _login(STAFF)["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        # /me
        r = requests.get(f"{API}/auth/me", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "staff"


# ---------- 2 & 3. AppointmentIn / AppointmentUpdate accept 'in_session' ----------
class TestAppointmentInSession:
    def test_post_appointment_in_session(self, admin_headers):
        # Need a practitioner_id and client_id
        clients = requests.get(f"{API}/clients", headers=admin_headers, timeout=15).json()
        assert len(clients) > 0, "No clients seeded"
        pr = requests.get(f"{API}/practitioners", headers=admin_headers, timeout=15)
        assert pr.status_code == 200, pr.text
        practitioners = pr.json()
        assert practitioners, "No practitioner seeded"

        start = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(minutes=32)).isoformat()
        payload = {
            "client_id": clients[0]["id"],
            "practitioner_id": practitioners[0]["id"],
            "start": start,
            "end": end,
            "status": "in_session",
            "visit_mode": "telehealth",
            "reason": "TEST_phase9_in_session_post",
        }
        r = requests.post(f"{API}/appointments", json=payload, headers=admin_headers, timeout=15)
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body["status"] == "in_session"
        assert body["visit_mode"] == "telehealth"
        assert body["id"]
        # cleanup
        requests.delete(f"{API}/appointments/{body['id']}", headers=admin_headers, timeout=15)

    def test_put_appointment_to_in_session(self, admin_headers):
        clients = requests.get(f"{API}/clients", headers=admin_headers, timeout=15).json()
        practitioners = requests.get(f"{API}/practitioners", headers=admin_headers, timeout=15).json()
        assert clients and practitioners

        # Create scheduled
        start = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(minutes=40)).isoformat()
        create = requests.post(
            f"{API}/appointments",
            json={
                "client_id": clients[0]["id"],
                "practitioner_id": practitioners[0]["id"],
                "start": start,
                "end": end,
                "status": "scheduled",
                "visit_mode": "telehealth",
                "reason": "TEST_phase9_in_session_put",
            },
            headers=admin_headers,
            timeout=15,
        )
        assert create.status_code in (200, 201), create.text
        appt = create.json()
        appt_id = appt["id"]
        try:
            # PUT with status=in_session — the iter5 bug
            r = requests.put(
                f"{API}/appointments/{appt_id}",
                json={"status": "in_session"},
                headers=admin_headers,
                timeout=15,
            )
            assert r.status_code == 200, f"PUT failed: {r.status_code} {r.text}"
            assert r.json()["status"] == "in_session"
            # Verify persistence via list endpoint (no single-GET on /appointments/{id})
            list_r = requests.get(f"{API}/appointments", headers=admin_headers, timeout=15)
            assert list_r.status_code == 200, list_r.text
            persisted = next((a for a in list_r.json() if a["id"] == appt_id), None)
            assert persisted is not None, "Appointment not in list after PUT"
            assert persisted["status"] == "in_session", f"Expected in_session, got {persisted['status']}"
        finally:
            requests.delete(f"{API}/appointments/{appt_id}", headers=admin_headers, timeout=15)


# ---------- 4. Regression smoke ----------
class TestRegressionSmoke:
    @pytest.mark.parametrize(
        "creds_label,creds",
        [("admin", ADMIN), ("practitioner", PRACTITIONER), ("staff", STAFF), ("alt_admin", ALT_ADMIN)],
    )
    def test_login_all_roles(self, creds_label, creds):
        data = _login(creds)
        assert data["access_token"]
        assert data["user"]["email"] == creds["email"]

    @pytest.mark.parametrize(
        "path",
        [
            "/appointments",
            "/clients",
            "/inventory",
            "/treatments",
            "/transactions",
        ],
    )
    def test_admin_get_endpoints(self, admin_headers, path):
        r = requests.get(f"{API}{path}", headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"GET {path} -> {r.status_code} {r.text}"
        body = r.json()
        # Most endpoints return list; some may return {items: [...]}.
        assert isinstance(body, (list, dict)), f"Unexpected response shape from {path}"
