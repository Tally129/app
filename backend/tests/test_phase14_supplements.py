"""Phase 14 — Auto-attach supplement directions when SOAP note references them."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://design-158.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@natmedsol.local", "Admin!2345")
PRACT = ("ravello@natmedsol.local", "Ravello!2345")
STAFF = ("frontdesk@natmedsol.local", "FrontDesk!2345")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def pract_tok():
    return _login(*PRACT)


@pytest.fixture(scope="module")
def staff_tok():
    return _login(*STAFF)


@pytest.fixture(scope="module")
def patient(pract_tok):
    """Register a fresh patient + ensure /clients row is linked via user_id."""
    nonce = uuid.uuid4().hex[:8]
    email = f"TEST_p14_{nonce}@example.com"
    pwd = "SafePass2026Long!"
    rr = requests.post(f"{API}/auth/register", json={
        "email": email, "password": pwd, "full_name": f"Q Q {nonce}", "phone": "+15551110000",
    }, timeout=20)
    assert rr.status_code == 200, rr.text
    pat_tok = rr.json()["access_token"]
    # Resolve client row via /clients/me
    me = requests.get(f"{API}/clients/me", headers=_h(pat_tok), timeout=15)
    assert me.status_code == 200, me.text
    client_id = me.json()["id"]
    return {"email": email, "password": pwd, "tok": pat_tok, "client_id": client_id}


@pytest.fixture(scope="module")
def other_patient():
    """A second registered patient to verify cross-client RBAC (403)."""
    nonce = uuid.uuid4().hex[:8]
    email = f"TEST_p14b_{nonce}@example.com"
    rr = requests.post(f"{API}/auth/register", json={
        "email": email, "password": "SafePass2026Long!", "full_name": f"Qq {nonce}", "phone": "+15551110001",
    }, timeout=20)
    assert rr.status_code == 200, rr.text
    tok = rr.json()["access_token"]
    me = requests.get(f"{API}/clients/me", headers=_h(tok), timeout=15)
    return {"tok": tok, "client_id": me.json()["id"]}


@pytest.fixture(scope="module")
def supp_sheet(admin_tok):
    """Create a unique 'Liver Detox Support' sheet (with nonce to avoid collisions)."""
    nonce = uuid.uuid4().hex[:6]
    title = f"Liver Detox Support {nonce}"
    payload = {
        "title": title,
        "summary": "Daily liver-support stack for phase-1/2 detoxification.",
        "items": [
            {"name": "Milk Thistle", "dose": "300mg", "frequency": "2x/day", "timing": "with meals"},
            {"name": "NAC", "dose": "600mg", "frequency": "1x/day", "timing": "morning"},
            {"name": "B-Complex", "dose": "1 cap", "frequency": "1x/day", "timing": "morning"},
        ],
    }
    r = requests.post(f"{API}/library/supplements", headers=_h(admin_tok), json=payload, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def supp_sheet2(admin_tok):
    nonce = uuid.uuid4().hex[:6]
    title = f"Adrenal Renew {nonce}"
    payload = {
        "title": title,
        "summary": "Adrenal support for HPA axis recovery.",
        "items": [
            {"name": "Ashwagandha", "dose": "500mg", "frequency": "2x/day"},
            {"name": "Rhodiola", "dose": "200mg", "frequency": "1x/day", "timing": "morning"},
        ],
    }
    r = requests.post(f"{API}/library/supplements", headers=_h(admin_tok), json=payload, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


# ============== Tests ==============

class TestSupplementSheet:
    def test_admin_creates_sheet(self, supp_sheet):
        assert supp_sheet["id"]
        assert "Liver Detox Support" in supp_sheet["title"]
        assert len(supp_sheet["items"]) == 3
        assert supp_sheet["active"] is True


class TestAutoAttach:
    def test_note_with_plan_referencing_sheet_creates_assignment(self, pract_tok, patient, supp_sheet):
        title = supp_sheet["title"]
        note_payload = {
            "client_id": patient["client_id"],
            "subjective": "Pt reports fatigue.",
            "objective": "BP 120/80.",
            "assessment": "Sluggish detox.",
            "plan": f"Start {title} for 30 days.",
        }
        r = requests.post(f"{API}/notes", headers=_h(pract_tok), json=note_payload, timeout=20)
        assert r.status_code == 200, r.text
        note1_id = r.json()["id"]

        # Verify via list endpoint (note: NoteOut doesn't expose auto_attached_supplements)
        time.sleep(0.5)
        rl = requests.get(f"{API}/clients/{patient['client_id']}/supplement-assignments",
                          headers=_h(pract_tok), timeout=15)
        assert rl.status_code == 200, rl.text
        rows = rl.json()
        match = [a for a in rows if a["sheet_id"] == supp_sheet["id"]]
        assert len(match) == 1, f"Expected 1 assignment for sheet, got {len(match)}: {rows}"
        a = match[0]
        assert a["sheet_title"] == title
        assert a["source"] == "auto_soap"
        assert a["active"] is True
        assert len(a["items_snapshot"]) == len(supp_sheet["items"])
        assert note1_id in a.get("note_ids", [])
        assert a["assigned_by_id"]
        # Stash for next tests
        pytest.note1_id = note1_id
        pytest.assignment_id = a["id"]

    def test_idempotency_second_note_same_sheet(self, pract_tok, patient, supp_sheet):
        title = supp_sheet["title"]
        note_payload = {
            "client_id": patient["client_id"],
            "subjective": "Follow-up visit.",
            "plan": f"Continue {title} as discussed.",
            "objective": "", "assessment": "",
        }
        r = requests.post(f"{API}/notes", headers=_h(pract_tok), json=note_payload, timeout=20)
        assert r.status_code == 200, r.text
        note2_id = r.json()["id"]

        time.sleep(0.5)
        rl = requests.get(f"{API}/clients/{patient['client_id']}/supplement-assignments",
                          headers=_h(pract_tok), timeout=15)
        rows = rl.json()
        match = [a for a in rows if a["sheet_id"] == supp_sheet["id"] and a["active"]]
        assert len(match) == 1, f"Expected idempotent — got {len(match)} active rows: {match}"
        a = match[0]
        # Both note ids attached
        assert pytest.note1_id in a["note_ids"]
        assert note2_id in a["note_ids"]
        # last_referenced_at >= assigned_at
        assert a["last_referenced_at"] >= a["assigned_at"]

    def test_note_without_reference_no_change(self, pract_tok, patient, supp_sheet):
        before = requests.get(f"{API}/clients/{patient['client_id']}/supplement-assignments",
                              headers=_h(pract_tok), timeout=15).json()
        r = requests.post(f"{API}/notes", headers=_h(pract_tok), json={
            "client_id": patient["client_id"],
            "subjective": "No supplement mention here.",
            "plan": "Recheck in 2 weeks.",
            "objective": "", "assessment": "",
        }, timeout=20)
        assert r.status_code == 200
        time.sleep(0.3)
        after = requests.get(f"{API}/clients/{patient['client_id']}/supplement-assignments",
                             headers=_h(pract_tok), timeout=15).json()
        assert len(after) == len(before), f"Count changed unexpectedly: {len(before)}→{len(after)}"

    def test_different_sheet_in_assessment_creates_second_assignment(self, pract_tok, patient, supp_sheet2):
        title = supp_sheet2["title"]
        r = requests.post(f"{API}/notes", headers=_h(pract_tok), json={
            "client_id": patient["client_id"],
            "subjective": "",
            "objective": "",
            "assessment": f"Patient would benefit from {title} stack.",
            "plan": "",
        }, timeout=20)
        assert r.status_code == 200
        time.sleep(0.3)
        rows = requests.get(f"{API}/clients/{patient['client_id']}/supplement-assignments",
                            headers=_h(pract_tok), timeout=15).json()
        match2 = [a for a in rows if a["sheet_id"] == supp_sheet2["id"]]
        assert len(match2) == 1
        assert match2[0]["sheet_title"] == title
        assert match2[0]["source"] == "auto_soap"


class TestRBAC:
    def test_client_can_get_own(self, patient):
        r = requests.get(f"{API}/clients/{patient['client_id']}/supplement-assignments",
                         headers=_h(patient["tok"]), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_client_forbidden_other(self, patient, other_patient):
        r = requests.get(f"{API}/clients/{other_patient['client_id']}/supplement-assignments",
                         headers=_h(patient["tok"]), timeout=15)
        assert r.status_code == 403

    def test_staff_cannot_manual_assign(self, staff_tok, patient, supp_sheet):
        r = requests.post(f"{API}/clients/{patient['client_id']}/supplement-assignments",
                          headers=_h(staff_tok), json={"sheet_id": supp_sheet["id"]}, timeout=15)
        assert r.status_code == 403


class TestManualAssignAndDelete:
    def test_practitioner_manual_assign(self, pract_tok, admin_tok, other_patient):
        # Use a fresh sheet to test 'manual' source flag
        s = requests.post(f"{API}/library/supplements", headers=_h(admin_tok), json={
            "title": f"Manual Sheet {uuid.uuid4().hex[:6]}",
            "summary": "Manual override test",
            "items": [{"name": "Vit D", "dose": "5000IU", "frequency": "1x/day"}],
        }, timeout=15).json()
        r = requests.post(f"{API}/clients/{other_patient['client_id']}/supplement-assignments",
                          headers=_h(pract_tok), json={"sheet_id": s["id"]}, timeout=15)
        assert r.status_code == 200, r.text
        a = r.json()
        assert a["source"] == "manual"
        assert a["sheet_id"] == s["id"]
        assert a["active"] is True
        pytest.manual_assignment_id = a["id"]
        pytest.manual_client_id = other_patient["client_id"]
        pytest.manual_sheet_id = s["id"]

    def test_delete_assignment_soft_deletes(self, pract_tok):
        cid = pytest.manual_client_id
        aid = pytest.manual_assignment_id
        r = requests.delete(f"{API}/clients/{cid}/supplement-assignments/{aid}",
                            headers=_h(pract_tok), timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        # Verify it no longer appears in active list
        rows = requests.get(f"{API}/clients/{cid}/supplement-assignments",
                            headers=_h(pract_tok), timeout=15).json()
        assert not any(x["id"] == aid for x in rows), "deleted assignment still listed"

    def test_audit_logs_present(self, admin_tok):
        # log_audit writes to audit_logs collection — check via admin audit endpoint if exists
        # filter by action via /admin/audit
        rc = requests.get(f"{API}/admin/audit?limit=50&action=supplement_assignment.create",
                          headers=_h(admin_tok), timeout=15)
        assert rc.status_code == 200, rc.text
        assert len(rc.json()) >= 1, "no supplement_assignment.create audit rows"
        rd = requests.get(f"{API}/admin/audit?limit=50&action=supplement_assignment.remove",
                          headers=_h(admin_tok), timeout=15)
        assert rd.status_code == 200, rd.text
        assert len(rd.json()) >= 1, "no supplement_assignment.remove audit rows"
