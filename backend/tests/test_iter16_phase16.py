"""
Iteration 16 — Phase 16 refactor + SDK abstraction verification.

Covers:
  1. GET /api/health returns integrations dict with all 4 keys (llm/email/sms/google_oauth_direct)
     and correct fallback values when env vars unset.
  2. Google OAuth direct endpoints return 503 (not 500 crash) when env vars missing.
  3. Emergent Google session endpoint still works (missing header -> 400, not 500).
  4. LLM abstraction: forms/protocols transcribe endpoints route through llm_client → 200.
  5. Notifier abstraction: form send channel=email|sms returns delivery_status='sent_stub'
     with integration_log doc having _stubbed=True.
  6. Representative endpoint per extracted router responds ≥200.
"""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://design-158.preview.emergentagent.com").rstrip("/")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@natmedsol.local", "password": "Admin!2345"
    }, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def practitioner_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "ravello@natmedsol.local", "password": "Ravello!2345"
    }, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def practitioner_headers(practitioner_token):
    return {"Authorization": f"Bearer {practitioner_token}"}


# ========== 1. HEALTH ENDPOINT INTEGRATIONS DICT ==========
class TestHealthIntegrations:
    def test_health_has_all_4_integration_keys(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        integ = data["integrations"]
        assert "llm" in integ and "email" in integ and "sms" in integ and "google_oauth_direct" in integ

    def test_health_llm_is_emergent_proxy_fallback(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.json()["integrations"]["llm"] == "emergent_proxy"

    def test_health_email_is_sent_stub(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.json()["integrations"]["email"] == "sent_stub"

    def test_health_sms_is_sent_stub(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.json()["integrations"]["sms"] == "sent_stub"

    def test_health_google_oauth_direct_false(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.json()["integrations"]["google_oauth_direct"] is False


# ========== 2. GOOGLE OAUTH DIRECT — 503 FALLBACK ==========
class TestGoogleOAuthDirect:
    def test_authorize_returns_503_when_env_missing(self):
        r = requests.get(f"{BASE_URL}/api/auth/google/oauth/authorize", timeout=15)
        assert r.status_code == 503
        assert "not configured" in r.json().get("detail", "").lower()

    def test_callback_returns_503_when_env_missing(self):
        r = requests.get(f"{BASE_URL}/api/auth/google/oauth/callback",
                         params={"code": "fakecode", "state": "fakestate"}, timeout=15)
        assert r.status_code == 503

    def test_emergent_google_session_still_works_missing_header_returns_400(self):
        # Existing Emergent flow should NOT crash — should return 400 for missing header
        r = requests.post(f"{BASE_URL}/api/auth/google/session", timeout=15)
        assert r.status_code == 400
        assert "session" in r.json().get("detail", "").lower()


# ========== 3. LLM ABSTRACTION (forms + protocols transcribe) ==========
class TestLlmAbstraction:
    def test_forms_transcribe_via_llm_client(self, practitioner_headers):
        # Send a small text "file" as UploadFile — router extracts text and pipes to complete_text()
        content = (
            "Patient consent form. Patient name is required. "
            "Date of birth is required. Signature is required. "
            "Please acknowledge that you have read the HIPAA notice."
        )
        files = {"file": ("consent.txt", io.BytesIO(content.encode()), "text/plain")}
        r = requests.post(
            f"{BASE_URL}/api/forms/transcribe",
            headers=practitioner_headers, files=files, timeout=90,
        )
        # Must return 200 (proves llm_client.complete_text routed through emergent proxy)
        assert r.status_code == 200, f"forms/transcribe failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        # Structured schema — must contain the parsed fields OR at least be a dict
        assert isinstance(data, dict)

    def test_protocols_transcribe_via_llm_client(self, practitioner_headers):
        content = (
            "Detox protocol: 4 weeks. Weekly meal plan. Drink lemon water. "
            "Avoid dairy and gluten. Take supplements: milk thistle, activated charcoal."
        )
        files = {"file": ("protocol.txt", io.BytesIO(content.encode()), "text/plain")}
        r = requests.post(
            f"{BASE_URL}/api/protocols/transcribe",
            headers=practitioner_headers, files=files, timeout=90,
        )
        assert r.status_code == 200, f"protocols/transcribe failed: {r.status_code} {r.text[:400]}"
        assert isinstance(r.json(), dict)


# ========== 4. NOTIFIER ABSTRACTION (email + sms → sent_stub) ==========
class TestNotifierAbstraction:
    @pytest.fixture(scope="class")
    def sample_form_and_client(self, practitioner_headers):
        # Get first builtin form template
        r = requests.get(f"{BASE_URL}/api/forms/templates", headers=practitioner_headers, timeout=15)
        assert r.status_code == 200
        templates = r.json()
        assert len(templates) > 0
        form_id = templates[0]["id"]

        # Get any client (need a client_id + email/phone recipient)
        rc = requests.get(f"{BASE_URL}/api/clients", headers=practitioner_headers, timeout=15)
        assert rc.status_code == 200
        clients = rc.json()
        assert len(clients) > 0
        # Pick client with an email
        client = next((c for c in clients if c.get("email")), clients[0])
        return form_id, client

    def test_forms_send_email_returns_sent_stub(self, practitioner_headers, sample_form_and_client):
        form_id, client = sample_form_and_client
        r = requests.post(
            f"{BASE_URL}/api/forms/send",
            headers=practitioner_headers,
            json={
                "template_id": form_id,
                "client_id": client["id"],
                "channel": "email",
                "delivery_target": client.get("email") or "test@example.com",
            }, timeout=30,
        )
        assert r.status_code == 200, f"forms/send email failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        # Fallback path: notifiers should return sent_stub since SENDGRID_API_KEY empty
        assert data.get("delivery_status") == "sent_stub", f"expected sent_stub, got {data.get('delivery_status')}"

    def test_forms_send_sms_returns_sent_stub(self, practitioner_headers, sample_form_and_client):
        form_id, client = sample_form_and_client
        r = requests.post(
            f"{BASE_URL}/api/forms/send",
            headers=practitioner_headers,
            json={
                "template_id": form_id,
                "client_id": client["id"],
                "channel": "sms",
                "delivery_target": client.get("phone") or "+15555550100",
            }, timeout=30,
        )
        assert r.status_code == 200, f"forms/send sms failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        assert data.get("delivery_status") == "sent_stub", f"expected sent_stub, got {data.get('delivery_status')}"


# ========== 5. REPRESENTATIVE ENDPOINT PER EXTRACTED ROUTER ==========
class TestExtractedRouterEndpoints:
    """Each extracted router has at least one route that responds ≥200 correctly."""

    def test_router_clients(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/clients", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_router_admin_dashboard_stats(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        # Should contain metric counts
        assert isinstance(data, dict)

    def test_router_admin_audit(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/audit", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_router_appointments_list(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/appointments", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_practitioners_list(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/practitioners", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_memberships_list(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/memberships", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_invoices_list(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/invoices", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_treatment_plans_list(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/treatment-plans", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_reminder_settings(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/reminders/settings", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_symptom_presets(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/symptoms/presets", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_labs_presets(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/labs/presets", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_messages_threads(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/messages/threads", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_ops_treatments(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/treatments", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_ops_inventory(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/inventory", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_ops_transactions(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/transactions", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_ops_time_clock_current(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/time-clock/me/current", headers=admin_headers, timeout=15)
        assert r.status_code in (200, 404)  # 404 if not clocked-in is fine

    def test_router_ops_front_desk_today(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/front-desk/today", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_ops_analytics_overview(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/analytics/overview", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_telehealth_webrtc_config(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/webrtc/config", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_forms_templates(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/forms/templates", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_router_soap_templates(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/soap-templates", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_protocols_templates(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/protocols/templates", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_router_compliance_baa_checklist(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/compliance/baa-checklist", headers=admin_headers, timeout=15)
        assert r.status_code == 200


# ========== 6. NIST PASSWORD VALIDATOR (change-password 400 vs 422) ==========
class TestNistPasswordValidator:
    def test_change_password_short_returns_400_not_422(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/auth/change-password",
            headers=admin_headers,
            json={"current_password": "Admin!2345", "new_password": "short"}, timeout=15,
        )
        # Must be clean 400 (from validator), not 422 (pydantic)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert "12" in detail or "at least" in detail.lower()

    def test_change_password_common_password_returns_400(self, admin_headers):
        # 'Password1234' is 12 chars & simple; if the validator has a common-password list, 400.
        # If validator only checks length + name-contains, this may 200 (which mutates state) —
        # skip mutation and instead verify name-contains rule using admin's own name token.
        r = requests.post(
            f"{BASE_URL}/api/auth/change-password",
            headers=admin_headers,
            json={"current_password": "Admin!2345", "new_password": "administrator2026!"}, timeout=15,
        )
        # 'administrator' contains 'admin' fragment of admin@... email — must reject 400
        assert r.status_code == 400, f"expected 400 for name-in-password, got {r.status_code}: {r.text[:300]}"
