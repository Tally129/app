"""Phase 13 backend tests:
- /api/library/classify (RBAC + form/protocol classification)
- /api/library/supplements CRUD
- /api/forms/send with channel email/sms/link + integration_log
- /api/visits/{appt_id}/recordings (list + bogus file id)
"""
import io
import os
import time
import uuid
import requests
import pytest
from urllib.parse import urlparse

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://design-158.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@natmedsol.local", "password": "Admin!2345"}
PRAC = {"email": "ravello@natmedsol.local", "password": "Ravello!2345"}
STAFF = {"email": "frontdesk@natmedsol.local", "password": "FrontDesk!2345"}

DETOX_DOCX_URL = (
    "https://customer-assets.emergentagent.com/job_design-158/artifacts/"
    "cwfz3lyv_Detox%20Protocol%20Template.docx"
)


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def prac_tok():
    return _login(PRAC)


@pytest.fixture(scope="module")
def staff_tok():
    return _login(STAFF)


@pytest.fixture(scope="module")
def client_tok():
    # create ephemeral patient
    email = f"TEST_p13_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": "SafePass2026Long!", "full_name": "Qz"
    }, timeout=20)
    assert r.status_code in (200, 201), r.text
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def detox_docx_bytes():
    r = requests.get(DETOX_DOCX_URL, timeout=30)
    assert r.status_code == 200
    return r.content


# ---------- Library: classify ----------

class TestLibraryClassify:
    def test_classify_protocol_docx_practitioner(self, prac_tok, detox_docx_bytes):
        files = {"file": ("Detox Protocol Template.docx", detox_docx_bytes,
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        r = requests.post(f"{API}/library/classify", files=files, headers=_h(prac_tok), timeout=90)
        assert r.status_code == 200, r.text
        body = r.json()
        cls = body.get("classification") or {}
        assert cls.get("type") == "protocol", f"type={cls.get('type')} body={body}"
        assert (cls.get("confidence") or 0) > 0.8
        draft = body.get("draft") or {}
        assert int(draft.get("weeks") or 0) >= 1, draft

    def test_classify_hipaa_text_form_admin(self, admin_tok):
        text = (
            "HIPAA Notice of Privacy Practices\n"
            "I, the undersigned, acknowledge receipt of the Notice of Privacy Practices.\n"
            "Patient Name: ____________________\n"
            "Date of Birth: __________\n"
            "Signature: ______________ Date: __________\n"
        )
        files = {"file": ("hipaa_notice.txt", text.encode("utf-8"), "text/plain")}
        r = requests.post(f"{API}/library/classify", files=files, headers=_h(admin_tok), timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        cls = body.get("classification") or {}
        assert cls.get("type") == "form", f"type={cls.get('type')} body={body}"
        sub = (cls.get("subcategory") or "").lower()
        assert "hipaa" in sub, f"subcategory={sub}"
        draft = body.get("draft") or {}
        fields = draft.get("fields") or []
        assert len(fields) >= 1, f"fields={fields}"

    def test_classify_rbac_client_forbidden(self, client_tok):
        files = {"file": ("x.txt", b"hello world this is a tiny doc for rbac testing only.", "text/plain")}
        r = requests.post(f"{API}/library/classify", files=files, headers=_h(client_tok), timeout=30)
        assert r.status_code == 403, f"got {r.status_code}: {r.text}"

    def test_classify_rbac_staff_allowed(self, staff_tok):
        text = "Patient consent for treatment. Name: ___ Date: ___ Signature: ___"
        files = {"file": ("consent.txt", text.encode(), "text/plain")}
        r = requests.post(f"{API}/library/classify", files=files, headers=_h(staff_tok), timeout=60)
        assert r.status_code == 200, r.text


# ---------- Library: supplements CRUD ----------

class TestLibrarySupplements:
    def test_supplements_crud_admin(self, admin_tok):
        title = f"TEST_supp_{uuid.uuid4().hex[:6]}"
        payload = {"title": title, "summary": "Test sheet", "items": [
            {"name": "Vit C", "dose": "1000mg", "frequency": "BID", "timing": "with food", "notes": ""}
        ]}
        r = requests.post(f"{API}/library/supplements", json=payload, headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]

        r = requests.get(f"{API}/library/supplements", headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert any(x["id"] == sid for x in rows)

        r = requests.delete(f"{API}/library/supplements/{sid}", headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200

    def test_supplements_get_practitioner_and_staff(self, prac_tok, staff_tok):
        for tok in (prac_tok, staff_tok):
            r = requests.get(f"{API}/library/supplements", headers=_h(tok), timeout=15)
            assert r.status_code == 200, r.text


# ---------- Forms send ----------

@pytest.fixture(scope="module")
def any_form_template_id(admin_tok):
    r = requests.get(f"{API}/forms/templates", headers=_h(admin_tok), timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    if rows:
        return rows[0]["id"]
    # create one
    payload = {"title": "TEST_phase13_form", "category": "intake",
               "fields": [{"key": "name", "type": "text", "label": "Name", "required": False}]}
    r = requests.post(f"{API}/forms/templates", json=payload, headers=_h(admin_tok), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _last_integration_log(admin_tok, service):
    r = requests.get(f"{API}/admin/integration-log", headers=_h(admin_tok),
                     params={"service": service, "limit": 5}, timeout=15)
    if r.status_code == 200:
        return r.json()
    return None


class TestFormsSend:
    def test_send_email_channel(self, admin_tok, any_form_template_id):
        target = f"TEST_p13_{uuid.uuid4().hex[:6]}@example.com"
        body = {"template_id": any_form_template_id, "channel": "email",
                "delivery_target": target, "expires_in_hours": 24}
        r = requests.post(f"{API}/forms/send", json=body, headers=_h(admin_tok), timeout=20)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out.get("channel") == "email"
        assert out.get("delivery_target") == target
        assert out.get("delivery_status") == "sent_stub", out

    def test_send_sms_channel(self, admin_tok, any_form_template_id):
        body = {"template_id": any_form_template_id, "channel": "sms",
                "delivery_target": "+15551234567", "expires_in_hours": 24}
        r = requests.post(f"{API}/forms/send", json=body, headers=_h(admin_tok), timeout=20)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out.get("channel") == "sms"
        assert out.get("delivery_status") == "sent_stub", out

    def test_send_link_no_target(self, admin_tok, any_form_template_id):
        body = {"template_id": any_form_template_id, "channel": "link", "expires_in_hours": 24}
        r = requests.post(f"{API}/forms/send", json=body, headers=_h(admin_tok), timeout=20)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out.get("channel") == "link"
        assert out.get("delivery_status") == "skipped", out
        assert "submit_url" in out and out["submit_url"].endswith(out.get("token", "")) or "/forms/respond/" in out.get("submit_url", "")


# ---------- Visit recordings ----------

@pytest.fixture(scope="module")
def fresh_appointment(admin_tok):
    # create a client + appointment
    email = f"TEST_p13_appt_{uuid.uuid4().hex[:6]}@example.com"
    r = requests.post(f"{API}/clients", json={"full_name": "TEST Phase13 Client", "email": email},
                      headers=_h(admin_tok), timeout=15)
    assert r.status_code in (200, 201), r.text
    client_id = r.json()["id"]
    # find a provider
    r = requests.get(f"{API}/admin/users", headers=_h(admin_tok), timeout=15)
    assert r.status_code == 200
    users = r.json()
    prov = next((u for u in users if u.get("role") == "practitioner"), None)
    assert prov, "no practitioner found"
    # create appt
    from datetime import datetime, timedelta, timezone
    start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
    payload = {"client_id": client_id, "provider_id": prov["id"], "start": start, "end": end,
               "visit_type": "telehealth"}
    r = requests.post(f"{API}/appointments", json=payload, headers=_h(admin_tok), timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


class TestVisitRecordings:
    def test_list_recordings_admin_empty(self, admin_tok, fresh_appointment):
        r = requests.get(f"{API}/visits/{fresh_appointment}/recordings",
                         headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_recordings_other_client_forbidden(self, client_tok, fresh_appointment):
        r = requests.get(f"{API}/visits/{fresh_appointment}/recordings",
                         headers=_h(client_tok), timeout=15)
        assert r.status_code == 403, f"got {r.status_code}"

    def test_download_recording_bogus_file_id(self, admin_tok, fresh_appointment):
        r = requests.get(f"{API}/visits/{fresh_appointment}/recordings/notarealid",
                         headers=_h(admin_tok), timeout=15)
        assert r.status_code in (400, 404), f"got {r.status_code}: {r.text}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
