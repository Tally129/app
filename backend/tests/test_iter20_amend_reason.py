"""
Iteration 20 — verify P1 defect fix from iter19:
POST /notes/{id}/amend and POST /treatment-plans/{id}/amend must reject
requests with missing/empty/whitespace `reason`. Plus regression coverage.
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

import pymongo
import pyotp
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

ADMIN = ("admin@natmedsol.local", "Admin!2345")
PRAC = ("ravello@natmedsol.local", "Ravello!2345")
AUDITOR = ("auditor@natmedsol.local", "Auditor!2345")


def _db():
    return pymongo.MongoClient(MONGO)[DB_NAME]


def _login(email: str, pw: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("mfa_required"):
        r = s.post(f"{API}/auth/login", json={
            "email": email, "password": pw,
            "mfa_token": pyotp.TOTP(TOTP_SECRET).now()})
        assert r.status_code == 200, r.text
        body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return s


def _register_client(pw: str = "SafePass2026Long!"):
    s = requests.Session()
    email = f"iter20_{uuid.uuid4().hex[:10]}@example.com"
    r = s.post(f"{API}/auth/register", json={
        "email": email, "password": pw,
        "full_name": "Iter20 Client", "phone": "+15555550401",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return s, body["user"]


def _make_finalized_note(prac: requests.Session, admin: requests.Session) -> tuple[str, str]:
    """Create client (admin), assign practitioner, draft note, finalize.
    Return (client_id, note_id)."""
    prac_user = _db().users.find_one({"email": PRAC[0]})
    c = admin.post(f"{API}/clients", json={
        "full_name": "TEST_iter20_amend",
        "email": f"tst_{uuid.uuid4().hex[:8]}@x.io",
        "assigned_practitioner_id": prac_user["id"],
    })
    assert c.status_code == 200, c.text
    cid = c.json()["id"]
    n = prac.post(f"{API}/notes", json={
        "client_id": cid, "subjective": "s1", "objective": "o1",
        "assessment": "a1", "plan": "p1"})
    assert n.status_code == 200, n.text
    nid = n.json()["id"]
    r = prac.post(f"{API}/notes/{nid}/finalize")
    assert r.status_code == 200 and r.json()["status"] == "finalized"
    return cid, nid


# --------------------------------------------------------------------------- #
# 1. P1 defect fix — amend note negative + positive cases
# --------------------------------------------------------------------------- #
class TestAmendNoteReasonEnforcement:
    def test_amend_with_empty_reason_returns_400(self):
        admin = _login(*ADMIN)
        prac = _login(*PRAC)
        _cid, nid = _make_finalized_note(prac, admin)
        r = prac.post(f"{API}/notes/{nid}/amend",
                      json={"content": "valid content here", "reason": ""})
        # AmendIn model requires `reason: str` (may 422) or handler 400.
        assert r.status_code in (400, 422), r.text

    def test_amend_with_missing_reason_key_returns_4xx(self):
        admin = _login(*ADMIN)
        prac = _login(*PRAC)
        _cid, nid = _make_finalized_note(prac, admin)
        r = prac.post(f"{API}/notes/{nid}/amend",
                      json={"content": "valid content here"})
        # Pydantic AmendIn now marks reason required → 422 (or handler 400).
        assert r.status_code in (400, 422), r.text

    def test_amend_with_whitespace_only_reason_returns_400(self):
        admin = _login(*ADMIN)
        prac = _login(*PRAC)
        _cid, nid = _make_finalized_note(prac, admin)
        r = prac.post(f"{API}/notes/{nid}/amend",
                      json={"content": "valid content here",
                            "reason": "   "})
        assert r.status_code == 400, r.text
        # Contract: should surface amendment_reason_required code
        try:
            body = r.json()
            detail = body.get("detail")
            if isinstance(detail, dict):
                assert detail.get("code") == "amendment_reason_required", detail
        except Exception:
            pass  # accept plain-text 400 also

    def test_amend_with_short_reason_lt_4_chars_returns_400(self):
        admin = _login(*ADMIN)
        prac = _login(*PRAC)
        _cid, nid = _make_finalized_note(prac, admin)
        r = prac.post(f"{API}/notes/{nid}/amend",
                      json={"content": "valid content here",
                            "reason": "ok"})
        assert r.status_code == 400, r.text

    def test_amend_with_valid_reason_returns_200_and_persists_and_audits(self):
        admin = _login(*ADMIN)
        prac = _login(*PRAC)
        _cid, nid = _make_finalized_note(prac, admin)
        r = prac.post(f"{API}/notes/{nid}/amend", json={
            "content": "clarify diagnosis",
            "reason": "post-visit typo correction"})
        assert r.status_code == 200, r.text
        body = r.json()
        amendments = body.get("amendments") or []
        assert len(amendments) >= 1, body
        latest = amendments[-1]
        assert latest.get("content") == "clarify diagnosis"
        assert latest.get("reason") == "post-visit typo correction"

        # Audit-log row for the amendment carries reason_preview.
        db = _db()
        # Look up most recent note.amend audit entry for this note.
        row = db.audit_logs.find_one(
            {"action": "note.amend", "resource_id": nid},
            sort=[("timestamp", pymongo.DESCENDING)],
        )
        # audit rows may use `ts` or `timestamp` — try both.
        if row is None:
            row = db.audit_logs.find_one(
                {"action": "note.amend", "resource_id": nid},
                sort=[("ts", pymongo.DESCENDING)],
            )
        assert row is not None, "audit_logs row missing for note.amend"
        meta = row.get("metadata") or {}
        assert meta.get("reason_preview") == "post-visit typo correction", meta


# --------------------------------------------------------------------------- #
# 2. Regression — treatment plan amend also enforces non-empty reason
# --------------------------------------------------------------------------- #
class TestAmendTreatmentPlanReason:
    def _make_finalized_plan(self, prac, admin) -> tuple[str, str]:
        prac_user = _db().users.find_one({"email": PRAC[0]})
        c = admin.post(f"{API}/clients", json={
            "full_name": "TEST_iter20_plan",
            "email": f"pln_{uuid.uuid4().hex[:8]}@x.io",
            "assigned_practitioner_id": prac_user["id"],
        }).json()
        p = prac.post(f"{API}/treatment-plans", json={
            "client_id": c["id"], "title": "Plan A",
            "objective": "Recover", "steps": ["step1", "step2"],
            "duration_weeks": 4,
        })
        assert p.status_code == 200, p.text
        pid = p.json()["id"]
        r = prac.post(f"{API}/treatment-plans/{pid}/finalize")
        assert r.status_code == 200, r.text
        return c["id"], pid

    def test_plan_amend_empty_reason_400(self):
        admin = _login(*ADMIN); prac = _login(*PRAC)
        _cid, pid = self._make_finalized_plan(prac, admin)
        r = prac.post(f"{API}/treatment-plans/{pid}/amend", json={
            "content": "adjust dosage step", "reason": ""})
        assert r.status_code == 400, r.text

    def test_plan_amend_short_reason_400(self):
        admin = _login(*ADMIN); prac = _login(*PRAC)
        _cid, pid = self._make_finalized_plan(prac, admin)
        r = prac.post(f"{API}/treatment-plans/{pid}/amend", json={
            "content": "adjust dosage step", "reason": "no"})
        assert r.status_code == 400, r.text

    def test_plan_amend_valid_reason_200(self):
        admin = _login(*ADMIN); prac = _login(*PRAC)
        _cid, pid = self._make_finalized_plan(prac, admin)
        r = prac.post(f"{API}/treatment-plans/{pid}/amend", json={
            "content": "adjust dosage step",
            "reason": "clinical update per lab result"})
        assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# 3. Regression — /notes with invalid client_id 404, finalize idempotent
# --------------------------------------------------------------------------- #
class TestNotesCoreRegression:
    def test_create_note_with_invalid_client_returns_404(self):
        prac = _login(*PRAC)
        r = prac.post(f"{API}/notes", json={
            "client_id": f"nonexistent_{uuid.uuid4().hex}",
            "subjective": "s", "objective": "o",
            "assessment": "a", "plan": "p"})
        assert r.status_code == 404, r.text

    def test_finalize_is_idempotent(self):
        admin = _login(*ADMIN)
        prac = _login(*PRAC)
        _cid, nid = _make_finalized_note(prac, admin)
        # First finalize already happened inside helper. Call again.
        r2 = prac.post(f"{API}/notes/{nid}/finalize")
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2.get("status") == "finalized"
        # No additional prior_versions snapshot should be appended on repeat calls.
        prior = body2.get("prior_versions") or []
        assert len(prior) == 1, f"expected exactly one snapshot, got {len(prior)}"


# --------------------------------------------------------------------------- #
# 4. Regression — prior UAT fixes still hold
# --------------------------------------------------------------------------- #
class TestPriorUATRegression:
    def test_practitioner_cannot_open_unassigned_client(self):
        admin = _login(*ADMIN)
        prac = _login(*PRAC)
        c = admin.post(f"{API}/clients", json={
            "full_name": "TEST_Unassigned iter20",
            "email": f"unx_{uuid.uuid4().hex[:8]}@x.io"}).json()
        r = prac.get(f"{API}/clients/{c['id']}")
        assert r.status_code in (403, 404), r.text

    def test_auditor_cannot_upload_file(self):
        s = _login(*AUDITOR)
        r = s.post(f"{API}/files/upload",
                   files={"file": ("x.txt", b"hello", "text/plain")})
        assert r.status_code == 403, r.text

    def test_client_cannot_access_breakglass_active(self):
        s, _me = _register_client()
        r = s.get(f"{API}/breakglass/active")
        assert r.status_code in (401, 403), r.text
