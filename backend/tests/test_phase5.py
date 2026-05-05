"""
Phase 4+ tests for NatMedSol EMR.
Covers: Provider Analytics endpoint, RBAC, regression smoke for Phase 4 endpoints,
PWA static asset reachability.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://design-158.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "tallyravello@gmail.com", "password": "TEST123"}
PRACTITIONER = {"email": "ravello@natmedsol.local", "password": "Ravello!2345"}


# -------- fixtures --------
@pytest.fixture(scope="session")
def admin_headers():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def practitioner_headers():
    r = requests.post(f"{API}/auth/login", json=PRACTITIONER, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def client_headers():
    email = "test_client_phase5@example.com"
    pwd = "ClientPass123"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": pwd, "full_name": "Test Client P5", "role": "client"
    }, timeout=15)
    if r.status_code not in (200, 201):
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------- Provider Analytics ----------
class TestAnalyticsOverview:
    def test_admin_default_30(self, admin_headers):
        r = requests.get(f"{API}/analytics/overview", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        # Top-level shape
        for key in ["window_days", "from", "to", "revenue", "appointments",
                    "clients", "top_treatments", "notes_by_provider", "low_stock_items"]:
            assert key in data, f"missing key: {key}"
        assert data["window_days"] == 30
        # Revenue subshape
        assert "total" in data["revenue"]
        assert "by_method" in data["revenue"]
        assert "series" in data["revenue"]
        assert isinstance(data["revenue"]["by_method"], dict)
        assert isinstance(data["revenue"]["series"], list)
        # Appointments subshape
        appt = data["appointments"]
        for k in ["total", "completed", "no_shows", "no_show_rate", "avg_duration_min"]:
            assert k in appt, f"appointments missing: {k}"
        # Clients
        assert "new_clients" in data["clients"]
        # top_treatments
        assert isinstance(data["top_treatments"], list)
        assert isinstance(data["notes_by_provider"], list)
        assert isinstance(data["low_stock_items"], int)

    @pytest.mark.parametrize("days", [7, 30, 90, 365])
    def test_admin_window_sizes(self, admin_headers, days):
        r = requests.get(f"{API}/analytics/overview?days={days}", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["window_days"] == days

    def test_practitioner_allowed(self, practitioner_headers):
        r = requests.get(f"{API}/analytics/overview?days=30", headers=practitioner_headers, timeout=20)
        assert r.status_code == 200, r.text

    def test_client_forbidden(self, client_headers):
        r = requests.get(f"{API}/analytics/overview?days=30", headers=client_headers, timeout=20)
        assert r.status_code == 403, r.text

    def test_unauthenticated_blocked(self):
        r = requests.get(f"{API}/analytics/overview?days=30", timeout=20)
        assert r.status_code in (401, 403), r.text


# ---------- Regression smoke for Phase 4 endpoints ----------
class TestPhase4Smoke:
    def test_login_admin(self):
        r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=15)
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_treatments_admin_list(self, admin_headers):
        r = requests.get(f"{API}/treatments", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_treatments_client_forbidden(self, client_headers):
        r = requests.get(f"{API}/treatments", headers=client_headers, timeout=15)
        assert r.status_code == 403

    def test_inventory_list(self, admin_headers):
        r = requests.get(f"{API}/inventory", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_transactions_list(self, admin_headers):
        r = requests.get(f"{API}/transactions", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_timeclock_status(self, admin_headers):
        r = requests.get(f"{API}/timeclock/status", headers=admin_headers, timeout=15)
        assert r.status_code in (200, 404)  # 404 if no punch yet

    def test_frontdesk_today(self, admin_headers):
        r = requests.get(f"{API}/front-desk/today", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_appointments_list(self, admin_headers):
        r = requests.get(f"{API}/appointments", headers=admin_headers, timeout=15)
        assert r.status_code == 200


# ---------- PWA static assets ----------
class TestPWAAssets:
    def test_manifest_reachable(self):
        r = requests.get(f"{BASE_URL}/manifest.json", timeout=15)
        assert r.status_code == 200, r.text
        m = r.json()
        assert "name" in m
        assert "icons" in m
        sizes = {i.get("sizes") for i in m["icons"]}
        assert "192x192" in sizes
        assert "512x512" in sizes
        assert m.get("theme_color", "").lower() == "#2f4a3a"
        assert m.get("start_url", "").startswith("/portal")

    def test_service_worker_reachable(self):
        r = requests.get(f"{BASE_URL}/service-worker.js", timeout=15)
        assert r.status_code == 200
        assert "javascript" in r.headers.get("content-type", "").lower() or len(r.text) > 0

    def test_icon_192_reachable(self):
        r = requests.get(f"{BASE_URL}/icons/icon-192.png", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")

    def test_icon_512_reachable(self):
        r = requests.get(f"{BASE_URL}/icons/icon-512.png", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")
