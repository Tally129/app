"""
Phase 4 backend tests for NatMedSol EMR.
Covers: Auth/MyAccount, Treatments, Inventory, POS, Transactions, TimeClock,
FrontDesk, Client Import, RBAC.
"""
import os
import io
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://design-158.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "tallyravello@gmail.com", "password": "TEST123"}
PRACTITIONER = {"email": "ravello@natmedsol.local", "password": "Ravello!2345"}


# -------- fixtures --------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def client_token():
    """Create or login a low-privilege client account for RBAC tests."""
    email = "test_client_phase4@example.com"
    pwd = "ClientPass123"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": pwd, "full_name": "Test Client P4", "role": "client"
    }, timeout=15)
    if r.status_code in (200, 201):
        return r.json()["access_token"]
    # already exists -> login
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def client_headers(client_token):
    return {"Authorization": f"Bearer {client_token}"}


@pytest.fixture(scope="session")
def admin_client_id(admin_headers):
    """Get a real client_id we can attach POS / front-desk to."""
    r = requests.get(f"{API}/clients", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    items = r.json()
    if items:
        return items[0]["id"]
    # otherwise create
    r = requests.post(f"{API}/clients", headers=admin_headers, json={
        "full_name": "TEST_POS Client", "email": "test_pos_client@example.com"
    }, timeout=15)
    return r.json()["id"]


# -------- Auth / MyAccount --------
class TestAuthAndAccount:
    def test_login_admin(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_get_me(self, admin_headers):
        r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN["email"]
        assert d["role"] == "admin"

    def test_profile_update(self, admin_headers):
        r = requests.put(f"{API}/auth/me", headers=admin_headers,
                         json={"full_name": "Tally Ravello", "phone": "555-0100"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["full_name"] == "Tally Ravello"

    def test_change_password_and_revert(self, admin_headers):
        """Change password to a temp value, verify login, then restore original hash via mongo.
        Note: ADMIN password 'TEST123' is only 7 chars and cannot be set via API
        (PasswordChange enforces min_length=8). We restore the original bcrypt
        hash directly so that documented credentials keep working."""
        import os as _os
        from pymongo import MongoClient
        from auth_utils import hash_password as _hash
        new_pwd = "TempPass!2345"
        mc = MongoClient(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = mc[_os.environ.get("DB_NAME", "test_database")]
        original_hash = db.users.find_one({"email": ADMIN["email"]})["password_hash"]
        try:
            r = requests.post(f"{API}/auth/change-password", headers=admin_headers,
                              json={"current_password": ADMIN["password"],
                                    "new_password": new_pwd}, timeout=15)
            assert r.status_code == 200, r.text
            r = requests.post(f"{API}/auth/login",
                              json={"email": ADMIN["email"], "password": new_pwd}, timeout=15)
            assert r.status_code == 200
        finally:
            # Restore original hash so TEST123 keeps working
            db.users.update_one({"email": ADMIN["email"]},
                                {"$set": {"password_hash": original_hash}})
        r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=15)
        assert r.status_code == 200, "Failed to restore TEST123 login"


# -------- Treatments --------
class TestTreatments:
    tid = None

    def test_create(self, admin_headers):
        r = requests.post(f"{API}/treatments", headers=admin_headers, json={
            "name": "TEST_Treatment", "category": "wellness",
            "duration_min": 45, "price": 120.0, "active": True
        }, timeout=15)
        assert r.status_code == 200, r.text
        TestTreatments.tid = r.json()["id"]
        assert r.json()["price"] == 120.0

    def test_list_includes(self, admin_headers):
        r = requests.get(f"{API}/treatments", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert any(t["id"] == TestTreatments.tid for t in r.json())

    def test_update(self, admin_headers):
        r = requests.put(f"{API}/treatments/{TestTreatments.tid}", headers=admin_headers, json={
            "name": "TEST_Treatment_v2", "duration_min": 60, "price": 150.0, "active": True
        }, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["price"] == 150.0

    def test_delete_admin_only(self, admin_headers):
        r = requests.delete(f"{API}/treatments/{TestTreatments.tid}", headers=admin_headers, timeout=15)
        assert r.status_code == 200


# -------- Inventory --------
class TestInventory:
    iid = None

    def test_create(self, admin_headers):
        r = requests.post(f"{API}/inventory", headers=admin_headers, json={
            "name": "TEST_Vitamin C", "stock": 20, "unit_price": 15.0, "low_stock_threshold": 5
        }, timeout=15)
        assert r.status_code == 200, r.text
        TestInventory.iid = r.json()["id"]
        assert r.json()["stock"] == 20

    def test_adjust(self, admin_headers):
        r = requests.post(f"{API}/inventory/{TestInventory.iid}/adjust", headers=admin_headers,
                          json={"delta": -3, "reason": "manual", "note": "test"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["stock"] == 17

    def test_update(self, admin_headers):
        r = requests.put(f"{API}/inventory/{TestInventory.iid}", headers=admin_headers, json={
            "name": "TEST_Vitamin C", "stock": 17, "unit_price": 18.0, "low_stock_threshold": 5
        }, timeout=15)
        assert r.status_code == 200
        assert r.json()["unit_price"] == 18.0


# -------- POS / Transactions --------
class TestPOS:
    txn_id = None

    def test_checkout_mixed(self, admin_headers, admin_client_id):
        # ensure inventory item to decrement
        inv = requests.post(f"{API}/inventory", headers=admin_headers, json={
            "name": "TEST_POS_Stock", "stock": 10, "unit_price": 25.0, "low_stock_threshold": 3
        }, timeout=15).json()
        payload = {
            "client_id": admin_client_id,
            "lines": [
                {"type": "treatment", "name": "Massage", "qty": 1, "unit_price": 100.0},
                {"type": "inventory", "ref_id": inv["id"], "name": "TEST_POS_Stock", "qty": 2, "unit_price": 25.0},
                {"type": "custom", "name": "Custom Tonic", "qty": 1, "unit_price": 30.0},
            ],
            "discount": 10.0,
            "tip": 5.0,
            "tax_rate": 0.08,
            "payment_method": "chase_pos",
        }
        r = requests.post(f"{API}/pos/checkout", headers=admin_headers, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        # subtotal = 100 + 50 + 30 = 180; after discount 170; tax = 13.6; total = 188.6
        assert abs(d["subtotal"] - 180.0) < 0.01
        assert abs(d["discount"] - 10.0) < 0.01
        assert abs(d["tax"] - 13.6) < 0.01
        assert abs(d["total"] - 188.6) < 0.01
        assert d["payment_method"] == "chase_pos"
        TestPOS.txn_id = d["id"]
        # verify decrement
        rinv = requests.get(f"{API}/inventory", headers=admin_headers, timeout=15)
        item = next(i for i in rinv.json() if i["id"] == inv["id"])
        assert item["stock"] == 8

    @pytest.mark.parametrize("method", ["cash", "check", "card_other", "stripe"])
    def test_checkout_payment_methods(self, admin_headers, admin_client_id, method):
        r = requests.post(f"{API}/pos/checkout", headers=admin_headers, json={
            "client_id": admin_client_id,
            "lines": [{"type": "custom", "name": "Quick Sale", "qty": 1, "unit_price": 50.0}],
            "payment_method": method,
        }, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["payment_method"] == method

    def test_transactions_filter_by_client(self, admin_headers, admin_client_id):
        r = requests.get(f"{API}/transactions", headers=admin_headers,
                         params={"client_id": admin_client_id}, timeout=15)
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        assert all(t.get("client_id") == admin_client_id for t in items)

    def test_receipt_pdf(self, admin_headers):
        assert TestPOS.txn_id, "need txn from prior test"
        r = requests.get(f"{API}/transactions/{TestPOS.txn_id}/receipt",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"


# -------- Time Clock --------
class TestTimeClock:
    def test_full_cycle(self, admin_headers):
        # punch in
        r = requests.post(f"{API}/time-clock/punch-in", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        # break start
        r = requests.post(f"{API}/time-clock/break-start", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        time.sleep(1)
        r = requests.post(f"{API}/time-clock/break-end", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        time.sleep(1)
        r = requests.post(f"{API}/time-clock/punch-out", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["clock_out"] is not None
        assert r.json()["total_minutes"] is not None
        # me
        r = requests.get(f"{API}/time-clock/me", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert any(e["id"] == eid for e in r.json())
        # all (admin)
        r = requests.get(f"{API}/time-clock/all", headers=admin_headers, timeout=15)
        assert r.status_code == 200


# -------- Front Desk --------
class TestFrontDesk:
    vid = None

    def test_check_in_walk_in(self, admin_headers, admin_client_id):
        r = requests.post(f"{API}/front-desk/check-in", headers=admin_headers, json={
            "client_id": admin_client_id, "walk_in": True, "room": "A1"
        }, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["walk_in"] is True
        assert d["room"] == "A1"
        TestFrontDesk.vid = d["id"]

    def test_today_list(self, admin_headers):
        r = requests.get(f"{API}/front-desk/today", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert any(v["id"] == TestFrontDesk.vid for v in r.json())

    def test_update_status_checked_out(self, admin_headers):
        r = requests.put(f"{API}/front-desk/{TestFrontDesk.vid}", headers=admin_headers,
                         json={"status": "checked_out", "room": "A1"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "checked_out"
        assert d["checked_out_at"] is not None


# -------- Client Import --------
class TestClientImport:
    def test_csv_import_with_dedupe(self, admin_headers):
        import uuid as _uuid
        u1 = f"test_imp_{_uuid.uuid4().hex[:6]}@example.com"
        u2 = f"test_imp_{_uuid.uuid4().hex[:6]}@example.com"
        csv_text = (
            "full_name,email,phone,dob,sex,address,emergency_contact\n"
            f"TEST_Import One,{u1},555-1111,1990-01-01,F,1 St,Mom 555\n"
            f"TEST_Import Two,{u2},555-2222,1985-02-02,M,2 St,Dad 555\n"
            f"TEST_Import Dup,{u1},555-9999,,,,\n"
        )
        files = {"file": ("clients.csv", csv_text, "text/csv")}
        r = requests.post(f"{API}/clients/import", headers=admin_headers,
                          files=files, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("imported", 0) >= 1
        assert d.get("skipped", 0) >= 1


# -------- RBAC --------
class TestRBAC:
    @pytest.mark.parametrize("method,path", [
        ("GET", "/inventory"),
        ("POST", "/inventory"),
        ("GET", "/treatments"),
        ("POST", "/treatments"),
        ("POST", "/pos/checkout"),
        ("GET", "/transactions"),
        ("GET", "/time-clock/all"),
        ("GET", "/front-desk/today"),
        ("POST", "/front-desk/check-in"),
        ("POST", "/clients/import"),
    ])
    def test_client_forbidden(self, client_headers, method, path):
        url = f"{API}{path}"
        if method == "GET":
            r = requests.get(url, headers=client_headers, timeout=15)
        else:
            r = requests.post(url, headers=client_headers, json={}, timeout=15)
        assert r.status_code == 403, f"{method} {path} expected 403, got {r.status_code}: {r.text[:200]}"
