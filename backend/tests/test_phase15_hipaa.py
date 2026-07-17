"""
Phase 15 — HIPAA technical hardening pass.

Verifies:
  * Security headers middleware (HSTS + friends)
  * NIST password policy on /auth/register + /auth/change-password
  * Auditor role: login + break-glass GET allowed, writes blocked, audit log stamped
  * /patient/data-export (client only) — shape + admin/practitioner forbidden
  * /clients/{id}/disclosures — own OK, other 403
  * /compliance/baa-checklist seed (8 rows) + PUT mark-signed
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://design-158.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@natmedsol.local", "Admin!2345")
PRAC = ("ravello@natmedsol.local", "Ravello!2345")
STAFF = ("frontdesk@natmedsol.local", "FrontDesk!2345")
AUDITOR = ("auditor@natmedsol.local", "Auditor!2345")


# ---------- helpers ----------

def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


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
    """Register a fresh client via /auth/register with a NIST-valid password."""
    email = f"TEST_p15_{uuid.uuid4().hex[:8]}@example.com"
    password = "PatientLongPass2026!"
    # Note: full_name must not share any 4+ char token with the password
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": password, "full_name": "Q A", "phone": None,
    }, timeout=15)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return {
        "email": email, "password": password, "token": data["access_token"],
        "user": data["user"], "user_id": data["user"]["id"],
    }


@pytest.fixture(scope="module")
def client_user_2():
    """A second fresh client used for the 'other client' 403 test."""
    email = f"TEST_p15b_{uuid.uuid4().hex[:8]}@example.com"
    password = "PatientLongPass2026!"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": password, "full_name": "Q B", "phone": None,
    }, timeout=15)
    assert r.status_code in (200, 201)
    return {"email": email, "token": r.json()["access_token"], "user_id": r.json()["user"]["id"]}


def _resolve_own_client_id(token):
    """Resolve /clients/me for a client-role user."""
    r = requests.get(f"{API}/clients/me", headers=_headers(token), timeout=15)
    assert r.status_code == 200, f"clients/me failed: {r.status_code} {r.text}"
    return r.json()["id"]


# ---------- (D) Security headers ----------

class TestSecurityHeaders:
    def test_hsts_and_friends_present(self):
        r = requests.get(f"{API}/", timeout=15)
        # Any status is OK — we just want to confirm middleware ran
        h = {k.lower(): v for k, v in r.headers.items()}
        assert "strict-transport-security" in h, f"HSTS missing. Headers: {list(h.keys())}"
        assert "max-age=" in h["strict-transport-security"]
        assert "includesubdomains" in h["strict-transport-security"].lower()
        assert h.get("x-frame-options", "").lower() == "deny"
        assert h.get("x-content-type-options", "").lower() == "nosniff"
        assert h.get("referrer-policy", "").lower() == "no-referrer"
        assert "permissions-policy" in h
        assert "geolocation=()" in h["permissions-policy"]


# ---------- (B) Password policy ----------

class TestPasswordPolicy:
    def test_register_rejects_weak_password(self):
        r = requests.post(f"{API}/auth/register", json={
            "email": f"TEST_p15weak_{uuid.uuid4().hex[:8]}@example.com",
            "password": "password1",
            "full_name": "Weak Test",
        }, timeout=15)
        assert r.status_code == 400
        detail = (r.json().get("detail") or "").lower()
        # Weak "password1" trips two rules: length OR common. Both acceptable.
        assert ("12 characters" in detail) or ("too common" in detail)

    def test_register_accepts_strong_password(self):
        email = f"TEST_p15strong_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", json={
            "email": email,
            "password": "PatientLongPass2026",
            "full_name": "Strong Test",
        }, timeout=15)
        assert r.status_code in (200, 201), f"expected 201, got {r.status_code} {r.text}"
        assert "access_token" in r.json()

    def test_change_password_rejects_short(self, client_user):
        # Log the user in fresh to avoid stale tokens.
        # Note: PasswordChange Pydantic model has min_length=8, so we use a 10-char
        # password that passes Pydantic but must be rejected by NIST validator (needs 12).
        r = requests.post(f"{API}/auth/change-password", headers=_headers(client_user["token"]),
                          json={"current_password": client_user["password"], "new_password": "TenChars12"},
                          timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
        assert "12 characters" in (r.json().get("detail") or "").lower()

    def test_change_password_accepts_strong_then_reverts(self, client_user):
        new_pw = "AnotherLongPass2026!"
        r = requests.post(f"{API}/auth/change-password", headers=_headers(client_user["token"]),
                          json={"current_password": client_user["password"], "new_password": new_pw},
                          timeout=15)
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        # Revert so subsequent tests using client_user["password"] still work
        # Need a fresh token (in case any refresh logic)
        new_token = _login(client_user["email"], new_pw)
        r2 = requests.post(f"{API}/auth/change-password", headers=_headers(new_token),
                           json={"current_password": new_pw, "new_password": client_user["password"]},
                           timeout=15)
        assert r2.status_code == 200


# ---------- (C) Auditor RBAC ----------

class TestAuditorRBAC:
    def test_auditor_login_role(self, auditor_token):
        # Decode via /auth/me
        r = requests.get(f"{API}/auth/me", headers=_headers(auditor_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "auditor"

    def test_auditor_get_clients_allowed(self, auditor_token):
        r = requests.get(f"{API}/clients", headers=_headers(auditor_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_auditor_post_client_forbidden(self, auditor_token):
        r = requests.post(f"{API}/clients", headers=_headers(auditor_token),
                          json={"full_name": "TEST auditor should not create", "email": f"TEST_p15_auditor_{uuid.uuid4().hex[:6]}@example.com"},
                          timeout=15)
        assert r.status_code == 403

    def test_auditor_break_glass_audit_row_written(self, auditor_token, admin_token):
        # Trigger a fresh GET as auditor
        requests.get(f"{API}/clients", headers=_headers(auditor_token), timeout=15)
        time.sleep(0.5)
        # Admin queries audit log for the break_glass_read row
        r = requests.get(f"{API}/admin/audit?action=auditor.break_glass_read&limit=10",
                         headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        rows = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        assert len(rows) >= 1, f"no auditor.break_glass_read rows found: {r.json()}"
        top = rows[0]
        assert top.get("action") == "auditor.break_glass_read"
        meta = top.get("metadata") or {}
        assert meta.get("emergency") is True


# ---------- (E) Patient data export ----------

class TestPatientDataExport:
    def test_client_export_success(self, client_user):
        r = requests.post(f"{API}/patient/data-export", headers=_headers(client_user["token"]), timeout=30)
        assert r.status_code == 200, f"got {r.status_code} {r.text}"
        j = r.json()
        for k in ["patient", "user_account", "appointments", "visit_notes", "treatment_plans",
                  "protocol_enrollments", "supplement_assignments", "form_submissions", "files", "billing"]:
            assert k in j, f"missing key {k} in export: {list(j.keys())}"
        # user_account.email must match
        assert j["user_account"]["email"].lower() == client_user["email"].lower()

    def test_admin_export_forbidden(self, admin_token):
        r = requests.post(f"{API}/patient/data-export", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 403

    def test_practitioner_export_forbidden(self, prac_token):
        r = requests.post(f"{API}/patient/data-export", headers=_headers(prac_token), timeout=15)
        assert r.status_code == 403


# ---------- (F) Accounting of disclosures ----------

class TestDisclosures:
    def test_client_own_disclosures_ok(self, client_user):
        own_cid = _resolve_own_client_id(client_user["token"])
        r = requests.get(f"{API}/clients/{own_cid}/disclosures", headers=_headers(client_user["token"]), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["client_id"] == own_cid
        assert "generated_at" in j
        assert isinstance(j["disclosures"], list)

    def test_client_other_disclosures_forbidden(self, client_user, client_user_2):
        other_cid = _resolve_own_client_id(client_user_2["token"])
        r = requests.get(f"{API}/clients/{other_cid}/disclosures", headers=_headers(client_user["token"]), timeout=15)
        assert r.status_code == 403


# ---------- (G) BAA checklist ----------

class TestBAAChecklist:
    def test_admin_get_baa_returns_8_rows(self, admin_token):
        r = requests.get(f"{API}/compliance/baa-checklist", headers=_headers(admin_token), timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 8, f"expected 8 rows, got {len(rows)}"
        keys = {row["key"] for row in rows}
        expected_keys = {"mongodb_atlas", "aws", "anthropic", "twilio", "sendgrid",
                         "google_workspace", "stripe", "emergent_migration"}
        assert keys == expected_keys, f"got keys: {keys}"

    def test_practitioner_get_baa_forbidden(self, prac_token):
        r = requests.get(f"{API}/compliance/baa-checklist", headers=_headers(prac_token), timeout=15)
        assert r.status_code == 403

    def test_staff_get_baa_forbidden(self, staff_token):
        r = requests.get(f"{API}/compliance/baa-checklist", headers=_headers(staff_token), timeout=15)
        assert r.status_code == 403

    def test_admin_put_mark_signed(self, admin_token):
        # Ensure seeded
        requests.get(f"{API}/compliance/baa-checklist", headers=_headers(admin_token), timeout=15)
        r = requests.put(f"{API}/compliance/baa-checklist/mongodb_atlas",
                         headers=_headers(admin_token),
                         json={"status": "signed", "notes": "TEST phase15 signed"},
                         timeout=15)
        assert r.status_code == 200, f"got {r.status_code} {r.text}"
        row = r.json()
        assert row["status"] == "signed"
        assert row["signed_at"] is not None
        assert row["signed_by"] is not None
        # Revert to not_started for idempotency of future runs
        requests.put(f"{API}/compliance/baa-checklist/mongodb_atlas",
                     headers=_headers(admin_token),
                     json={"status": "not_started", "notes": ""},
                     timeout=15)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
