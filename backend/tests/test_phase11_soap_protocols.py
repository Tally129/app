"""Phase 11 - SOAP Templates hub + Detox Protocols tests."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("admin@natmedsol.local", "Admin!2345"),
    "practitioner": ("ravello@natmedsol.local", "Ravello!2345"),
    "staff": ("frontdesk@natmedsol.local", "FrontDesk!2345"),
}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    return data.get("access_token") or data.get("token")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="session")
def admin_token():
    return _login(*CREDS["admin"])


@pytest.fixture(scope="session")
def practitioner_token():
    return _login(*CREDS["practitioner"])


@pytest.fixture(scope="session")
def staff_token():
    return _login(*CREDS["staff"])


@pytest.fixture(scope="session")
def client_ctx(admin_token):
    """Create a brand-new client (user + linked client record) for protocol tests."""
    ts = int(time.time())
    email = f"TEST_phase11_{ts}@example.com"
    password = "TestClient!2345"
    # Register as client
    r = requests.post(f"{API}/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "TEST P11 Client",
        "role": "client",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text[:300]
    ctok = r.json().get("access_token") or r.json().get("token")
    # Auth register auto-creates a linked client record. Find it via admin.
    me = requests.get(f"{API}/auth/me", headers=_h(ctok), timeout=10).json()
    user_id = me["id"]
    all_clients = requests.get(f"{API}/clients", headers=_h(admin_token), timeout=15).json()
    linked = [c for c in all_clients if c.get("user_id") == user_id]
    assert linked, f"no client auto-created for user {user_id}"
    client_id = linked[0]["id"]
    return {"email": email, "password": password, "token": ctok, "user_id": user_id, "client_id": client_id}


# =================== SOAP TEMPLATES ===================
class TestSoapTemplates:
    def test_seeded_templates_present(self, admin_token):
        r = requests.get(f"{API}/soap-templates", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text[:300]
        items = r.json()
        assert isinstance(items, list)
        titles = [t.get("title", "") for t in items]
        assert any("General wellness follow-up" in t for t in titles), f"missing General wellness: {titles}"
        assert any("Telehealth check-in" in t for t in titles), f"missing Telehealth: {titles}"
        assert len(items) >= 2

    def test_practitioner_can_create(self, practitioner_token):
        payload = {
            "title": "TEST_PH11 Custom SOAP",
            "category": "general",
            "subjective": "S-test",
            "objective": "O-test",
            "assessment": "A-test",
            "plan": "P-test",
            "active": True,
        }
        r = requests.post(f"{API}/soap-templates", headers=_h(practitioner_token), json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text[:300]
        data = r.json()
        assert data["title"] == "TEST_PH11 Custom SOAP"
        assert data["subjective"] == "S-test"
        # PUT update
        upd = {**payload, "subjective": "S-updated"}
        r = requests.put(f"{API}/soap-templates/{data['id']}", headers=_h(practitioner_token), json=upd, timeout=15)
        assert r.status_code == 200
        assert r.json()["subjective"] == "S-updated"
        # Verify persistence via GET
        r = requests.get(f"{API}/soap-templates", headers=_h(practitioner_token), timeout=15)
        found = [t for t in r.json() if t["id"] == data["id"]]
        assert found and found[0]["subjective"] == "S-updated"
        # Cleanup via admin
        admin_tok = _login(*CREDS["admin"])
        r = requests.delete(f"{API}/soap-templates/{data['id']}", headers=_h(admin_tok), timeout=15)
        assert r.status_code in (200, 204)

    def test_staff_cannot_create(self, staff_token):
        r = requests.post(f"{API}/soap-templates", headers=_h(staff_token), json={
            "title": "TEST_x", "subjective": "", "objective": "", "assessment": "", "plan": ""
        }, timeout=15)
        assert r.status_code == 403, r.text[:200]

    def test_client_cannot_create(self, client_ctx):
        r = requests.post(f"{API}/soap-templates", headers=_h(client_ctx["token"]), json={
            "title": "TEST_x", "subjective": "", "objective": "", "assessment": "", "plan": ""
        }, timeout=15)
        assert r.status_code == 403, r.text[:200]

    def test_staff_cannot_delete(self, staff_token, admin_token):
        # Create one as admin to attempt delete via staff
        payload = {"title": "TEST_PH11_delete_me", "subjective": "", "objective": "", "assessment": "", "plan": ""}
        r = requests.post(f"{API}/soap-templates", headers=_h(admin_token), json=payload, timeout=15)
        assert r.status_code in (200, 201)
        tid = r.json()["id"]
        r = requests.delete(f"{API}/soap-templates/{tid}", headers=_h(staff_token), timeout=15)
        assert r.status_code == 403
        # Cleanup
        requests.delete(f"{API}/soap-templates/{tid}", headers=_h(admin_token), timeout=10)


# =================== NOTES /all practitioner filter ===================
class TestNotesAllFilter:
    def test_practitioner_id_filter(self, admin_token, practitioner_token):
        # Get practitioner ID
        me = requests.get(f"{API}/auth/me", headers=_h(practitioner_token), timeout=10).json()
        pid = me["id"]
        r = requests.get(f"{API}/notes/all?practitioner_id={pid}", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text[:300]
        items = r.json()
        assert isinstance(items, list)
        # All returned notes should belong to this practitioner
        for n in items:
            assert n.get("practitioner_id") == pid, f"leaked note: {n}"


# =================== PROTOCOLS ===================
class TestProtocolTemplates:
    def test_builtin_detox_seeded(self, admin_token):
        r = requests.get(f"{API}/protocols/templates", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text[:300]
        items = r.json()
        assert isinstance(items, list) and len(items) >= 1
        nms = [t for t in items if "Natural Medical Solutions" in t.get("title", "") and "Detox" in t.get("title", "")]
        assert nms, f"Built-in NMS Detox not found: {[t.get('title') for t in items]}"
        tpl = nms[0]
        assert tpl.get("weeks") == 4
        assert tpl.get("sessions_per_week") == 2
        assert tpl.get("builtin") is True


class TestProtocolEnrollments:
    def test_create_accept_session_complete_flow(self, admin_token, practitioner_token, client_ctx):
        # Get built-in detox template
        r = requests.get(f"{API}/protocols/templates", headers=_h(practitioner_token), timeout=15)
        tpls = r.json()
        nms = [t for t in tpls if "Natural Medical Solutions" in t.get("title", "")][0]
        # Create enrollment as practitioner with weeks=2 spw=3 (6 sessions)
        payload = {
            "template_id": nms["id"],
            "client_id": client_ctx["client_id"],
            "weeks": 2,
            "sessions_per_week": 3,
        }
        r = requests.post(f"{API}/protocols/enrollments", headers=_h(practitioner_token), json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text[:400]
        enr = r.json()
        assert enr["status"] == "proposed"
        assert enr["weeks"] == 2
        assert enr["sessions_per_week"] == 3
        assert len(enr["sessions"]) == 6
        assert enr.get("accepted_at") is None

        enr_id = enr["id"]

        # Client RBAC: client should only see own enrollments
        r = requests.get(f"{API}/protocols/enrollments", headers=_h(client_ctx["token"]), timeout=15)
        assert r.status_code == 200
        my = r.json()
        assert any(e["id"] == enr_id for e in my), "client cannot see own proposed enrollment"
        for e in my:
            assert e["client_id"] == client_ctx["client_id"]

        # Client decides to accept
        r = requests.post(f"{API}/protocols/enrollments/{enr_id}/decision",
                          headers=_h(client_ctx["token"]), json={"decision": "accept"}, timeout=15)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["status"] == "active"
        assert r.json()["accepted_at"] is not None

        # Verify via GET
        r = requests.get(f"{API}/protocols/enrollments/{enr_id}", headers=_h(admin_token), timeout=10)
        assert r.json()["status"] == "active"

        # Mark all 6 sessions complete; on last one status -> completed
        for w in (1, 2):
            for s in (1, 2, 3):
                r = requests.post(f"{API}/protocols/enrollments/{enr_id}/sessions",
                                  headers=_h(practitioner_token),
                                  json={"week": w, "session": s, "completed": True}, timeout=15)
                assert r.status_code == 200, r.text[:300]
        final = r.json()
        assert final["status"] == "completed", f"expected completed got {final['status']}"
        assert final.get("completed_at") is not None
        # Each session should have completed_by_name stamp
        for sess in final["sessions"]:
            assert sess["completed"] is True
            assert sess.get("completed_by_name"), f"missing completed_by_name for {sess}"

    def test_decline_flow(self, practitioner_token, client_ctx):
        r = requests.get(f"{API}/protocols/templates", headers=_h(practitioner_token), timeout=15)
        nms = [t for t in r.json() if "Natural Medical Solutions" in t.get("title", "")][0]
        r = requests.post(f"{API}/protocols/enrollments", headers=_h(practitioner_token), json={
            "template_id": nms["id"],
            "client_id": client_ctx["client_id"],
            "weeks": 1,
            "sessions_per_week": 1,
        }, timeout=15)
        assert r.status_code in (200, 201)
        enr_id = r.json()["id"]
        r = requests.post(f"{API}/protocols/enrollments/{enr_id}/decision",
                          headers=_h(client_ctx["token"]),
                          json={"decision": "decline", "note": "not for me"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "declined"

    def test_staff_cannot_create_enrollment(self, staff_token, client_ctx, practitioner_token):
        r = requests.get(f"{API}/protocols/templates", headers=_h(practitioner_token), timeout=15)
        nms = [t for t in r.json() if "Natural Medical Solutions" in t.get("title", "")][0]
        r = requests.post(f"{API}/protocols/enrollments", headers=_h(staff_token), json={
            "template_id": nms["id"], "client_id": client_ctx["client_id"], "weeks": 1, "sessions_per_week": 1,
        }, timeout=15)
        assert r.status_code == 403

    def test_client_cannot_see_others(self, admin_token, practitioner_token, client_ctx):
        # Create enrollment for a different client (use admin's clients)
        r = requests.get(f"{API}/clients", headers=_h(admin_token), timeout=15)
        others = [c for c in r.json() if c["id"] != client_ctx["client_id"]]
        if not others:
            pytest.skip("no other clients to test cross-tenant isolation")
        other = others[0]
        r = requests.get(f"{API}/protocols/templates", headers=_h(practitioner_token), timeout=15)
        nms = [t for t in r.json() if "Natural Medical Solutions" in t.get("title", "")][0]
        r = requests.post(f"{API}/protocols/enrollments", headers=_h(practitioner_token), json={
            "template_id": nms["id"], "client_id": other["id"], "weeks": 1, "sessions_per_week": 1,
        }, timeout=15)
        assert r.status_code in (200, 201)
        other_enr_id = r.json()["id"]
        # Client should NOT see this enrollment
        r = requests.get(f"{API}/protocols/enrollments", headers=_h(client_ctx["token"]), timeout=15)
        assert all(e["id"] != other_enr_id for e in r.json())
        # Direct GET should 403
        r = requests.get(f"{API}/protocols/enrollments/{other_enr_id}", headers=_h(client_ctx["token"]), timeout=15)
        assert r.status_code == 403
