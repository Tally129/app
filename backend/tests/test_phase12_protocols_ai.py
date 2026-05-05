"""Phase 12 — Protocols AI Transcribe / Generate endpoints + regression smoke."""
import io
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

# ---------------- Fixtures ----------------

def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def tok_practitioner():
    return _login("ravello@natmedsol.local", "Ravello!2345")


@pytest.fixture(scope="session")
def tok_admin():
    return _login("admin@natmedsol.local", "Admin!2345")


@pytest.fixture(scope="session")
def tok_staff():
    return _login("frontdesk@natmedsol.local", "FrontDesk!2345")


@pytest.fixture(scope="session")
def tok_client():
    # Register an ephemeral patient
    email = f"TEST_p12_{int(time.time())}@example.com"
    rr = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "Pass!2345", "full_name": "TEST Phase12 Patient"},
        timeout=20,
    )
    assert rr.status_code in (200, 201), rr.text
    return rr.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------- 4-role login smoke ----------------
class TestAuthLoginSmoke:
    def test_admin_login(self):
        assert _login("admin@natmedsol.local", "Admin!2345")

    def test_practitioner_login(self):
        assert _login("ravello@natmedsol.local", "Ravello!2345")

    def test_staff_login(self):
        assert _login("frontdesk@natmedsol.local", "FrontDesk!2345")

    def test_alt_admin_login(self):
        # seeded alt admin
        assert _login("tallyravello@gmail.com", "TEST123")


# ---------------- POST /api/protocols/generate ----------------
class TestProtocolGenerate:
    def test_generate_as_practitioner_returns_valid_draft(self, tok_practitioner):
        r = requests.post(
            f"{BASE_URL}/api/protocols/generate",
            headers=_h(tok_practitioner),
            json={"prompt": "6-week liver detox with twice-weekly IV vitamin C, anti-inflammatory diet, no alcohol"},
            timeout=45,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        d = r.json()
        assert isinstance(d.get("title"), str) and len(d["title"]) > 3
        assert d["weeks"] >= 4, f"weeks={d.get('weeks')}"
        assert d["sessions_per_week"] >= 1
        assert isinstance(d.get("foods_recommended"), list) and len(d["foods_recommended"]) > 5
        assert isinstance(d.get("foods_avoid"), list) and len(d["foods_avoid"]) > 5

    def test_generate_as_staff_forbidden(self, tok_staff):
        r = requests.post(
            f"{BASE_URL}/api/protocols/generate",
            headers=_h(tok_staff),
            json={"prompt": "Short detox"},
            timeout=20,
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text}"

    def test_generate_as_client_forbidden(self, tok_client):
        r = requests.post(
            f"{BASE_URL}/api/protocols/generate",
            headers=_h(tok_client),
            json={"prompt": "Short detox"},
            timeout=20,
        )
        assert r.status_code == 403


# ---------------- POST /api/protocols/transcribe ----------------
DOCX_URL = "https://customer-assets.emergentagent.com/job_design-158/artifacts/cwfz3lyv_Detox%20Protocol%20Template.docx"


@pytest.fixture(scope="module")
def detox_docx_bytes():
    r = requests.get(DOCX_URL, timeout=30)
    assert r.status_code == 200, f"fetch docx failed: {r.status_code}"
    return r.content


class TestProtocolTranscribe:
    def test_transcribe_docx_as_practitioner(self, tok_practitioner, detox_docx_bytes):
        files = {
            "file": (
                "Detox Protocol Template.docx",
                io.BytesIO(detox_docx_bytes),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        headers = {"Authorization": f"Bearer {tok_practitioner}"}
        r = requests.post(
            f"{BASE_URL}/api/protocols/transcribe", headers=headers, files=files, timeout=60
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        d = r.json()
        assert "detox" in (d.get("title") or "").lower() or "detoxification" in (d.get("title") or "").lower(), d.get("title")
        assert isinstance(d.get("foods_recommended"), list) and len(d["foods_recommended"]) > 10, len(d.get("foods_recommended") or [])

    def test_transcribe_as_staff_forbidden(self, tok_staff, detox_docx_bytes):
        files = {"file": ("x.docx", io.BytesIO(detox_docx_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        headers = {"Authorization": f"Bearer {tok_staff}"}
        r = requests.post(f"{BASE_URL}/api/protocols/transcribe", headers=headers, files=files, timeout=30)
        assert r.status_code == 403, r.text

    def test_transcribe_as_client_forbidden(self, tok_client, detox_docx_bytes):
        files = {"file": ("x.docx", io.BytesIO(detox_docx_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        headers = {"Authorization": f"Bearer {tok_client}"}
        r = requests.post(f"{BASE_URL}/api/protocols/transcribe", headers=headers, files=files, timeout=30)
        assert r.status_code == 403


# ---------------- Regression smoke ----------------
class TestRegressionSmoke:
    def test_protocols_templates_list(self, tok_admin):
        r = requests.get(f"{BASE_URL}/api/protocols/templates", headers=_h(tok_admin), timeout=15)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 1
        # Built-in NMS Detox should exist
        titles = [(t.get("title") or "").lower() for t in arr]
        assert any("detox" in t for t in titles)

    def test_forms_transcribe_still_works_regression(self, tok_practitioner, detox_docx_bytes):
        # Regression: the existing /api/forms/transcribe endpoint must still parse a DOCX for a provider.
        files = {"file": ("f.docx", io.BytesIO(detox_docx_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        headers = {"Authorization": f"Bearer {tok_practitioner}"}
        r = requests.post(f"{BASE_URL}/api/forms/transcribe", headers=headers, files=files, timeout=45)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        d = r.json()
        assert isinstance(d.get("title"), str) and len(d["title"]) > 2

    def test_protocols_enrollments_create(self, tok_practitioner, tok_admin):
        # Pick a template
        tr = requests.get(f"{BASE_URL}/api/protocols/templates", headers=_h(tok_practitioner), timeout=15)
        tpl = tr.json()[0]
        # Pick a client — admin has broader access
        cr = requests.get(f"{BASE_URL}/api/clients", headers=_h(tok_admin), timeout=15)
        assert cr.status_code == 200
        clients = cr.json()
        if not clients:
            pytest.skip("No clients available")
        client = clients[0]
        r = requests.post(
            f"{BASE_URL}/api/protocols/enrollments",
            headers=_h(tok_practitioner),
            json={
                "template_id": tpl["id"],
                "client_id": client["id"],
                "weeks": 2,
                "sessions_per_week": 2,
                "custom_note": "TEST phase12 regression smoke",
            },
            timeout=20,
        )
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        enr = r.json()
        assert enr["status"] == "proposed"
        assert len(enr["sessions"]) == 4
