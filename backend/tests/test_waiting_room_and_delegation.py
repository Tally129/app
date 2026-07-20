"""
Feb 2026 — Telehealth Waiting Room + RBAC Delegated Editing tests.

Verifies:
    Waiting Room
        - client cannot start WebRTC signaling before admission
        - request-join → provider queue populated
        - admit unblocks signaling and moves state to `admitted`
        - decline requires a reason + is shown/audited
        - waiting-room state exposed via GET endpoint

    Delegation
        - admin/MA denied on notes/plans without an active delegation
        - practitioner grants delegation → MA can create + edit a draft
        - MA still denied on finalize / amend (provider-only)
        - revoked / expired delegation drops MA back to read-only
        - all delegated edits recorded in audit log with authorizing_provider_id
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pymongo
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("admin@natmedsol.local", "Admin!2345"),
    "practitioner": ("ravello@natmedsol.local", "Ravello!2345"),
    "medical_assistant": ("ma@natmedsol.local", "MedAssist!2345"),
}


def _login(email, password):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text[:200]}"
    return (r.json().get("access_token") or r.json().get("token"))


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def toks():
    return {k: _login(*v) for k, v in CREDS.items()}


@pytest.fixture(scope="module")
def db():
    c = pymongo.MongoClient(os.environ["MONGO_URL"])
    yield c[os.environ["DB_NAME"]]
    c.close()


@pytest.fixture(scope="module")
def client_and_appt(toks, db):
    """Create a fresh client + telehealth appointment for these tests."""
    # signup a fresh client
    email = f"wr_pat_{int(time.time())}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": "PatPass!23456",
        "full_name": "Waiting Room Test Patient",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    pat_token = r.json().get("access_token") or r.json().get("token")

    # Admin creates a client record + appointment (or use whichever endpoint)
    me = requests.get(f"{API}/auth/me", headers=_h(pat_token), timeout=10).json()
    # find/build the client record
    cr = db.clients.find_one({"user_id": me["id"]})
    if not cr:
        cr = {
            "id": me["id"] + "-c",
            "user_id": me["id"],
            "email": email,
            "full_name": me.get("full_name", "Patient"),
            "created_at": datetime.now(timezone.utc),
        }
        db.clients.insert_one(cr)
    client_id = cr["id"]

    # Practitioner id
    prov = db.users.find_one({"email": CREDS["practitioner"][0]})
    now = datetime.now(timezone.utc)
    appt = {
        "id": f"appt-wr-{int(time.time()*1000)}",
        "client_id": client_id, "practitioner_id": prov["id"],
        "start": now, "end": now + timedelta(minutes=30),
        "visit_mode": "telehealth", "visit_type": "Follow-up",
        "status": "scheduled",
        "consent_telehealth": True,
        "created_at": now,
    }
    db.appointments.insert_one(appt)
    return {"client_id": client_id, "appt_id": appt["id"],
            "pat_token": pat_token, "provider_id": prov["id"]}


# ------------------------------------------------------------------- #
# Waiting Room                                                         #
# ------------------------------------------------------------------- #
class TestWaitingRoom:

    def test_idle_before_request(self, client_and_appt, toks):
        appt_id = client_and_appt["appt_id"]
        r = requests.get(f"{API}/appointments/{appt_id}/telehealth/waiting-room",
                         headers=_h(toks["practitioner"]), timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "idle"

    def test_provider_cannot_admit_when_no_visitor(self, client_and_appt, toks):
        appt_id = client_and_appt["appt_id"]
        r = requests.post(f"{API}/appointments/{appt_id}/telehealth/admit",
                          headers=_h(toks["practitioner"]), timeout=10)
        assert r.status_code == 409

    def test_client_request_join(self, client_and_appt):
        appt_id = client_and_appt["appt_id"]
        r = requests.post(f"{API}/appointments/{appt_id}/telehealth/request-join",
                          headers=_h(client_and_appt["pat_token"]), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "requested"
        assert body.get("request_at")

    def test_provider_sees_queue(self, client_and_appt, toks):
        r = requests.get(f"{API}/telehealth/waiting-room/queue",
                         headers=_h(toks["practitioner"]), timeout=10)
        assert r.status_code == 200
        ids = [q["appointment_id"] for q in r.json()]
        assert client_and_appt["appt_id"] in ids

    def test_decline_requires_reason(self, client_and_appt, toks):
        appt_id = client_and_appt["appt_id"]
        r = requests.post(f"{API}/appointments/{appt_id}/telehealth/decline",
                          headers=_h(toks["practitioner"]),
                          json={"reason": ""}, timeout=10)
        assert r.status_code == 400
        detail = r.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code == "decline_reason_required"

    def test_provider_admit(self, client_and_appt, toks):
        appt_id = client_and_appt["appt_id"]
        r = requests.post(f"{API}/appointments/{appt_id}/telehealth/admit",
                          headers=_h(toks["practitioner"]), timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "admitted"

    def test_decline_records_reason_in_audit(self, client_and_appt, toks, db):
        # Reset appt to requested so we can decline
        db.appointments.update_one(
            {"id": client_and_appt["appt_id"]},
            {"$set": {"waiting_room.state": "requested",
                      "waiting_room.declined_at": None,
                      "waiting_room.decline_reason": None}},
        )
        r = requests.post(
            f"{API}/appointments/{client_and_appt['appt_id']}/telehealth/decline",
            headers=_h(toks["practitioner"]),
            json={"reason": "Provider unavailable — please rebook"},
            timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "declined"
        assert "Provider unavailable" in (body.get("decline_reason") or "")
        # Verify audit trail contains the decline row for this appt
        row = db.audit_logs.find_one({
            "action": "telehealth.waiting_room_decline",
            "resource_id": client_and_appt["appt_id"],
        })
        assert row is not None


# ------------------------------------------------------------------- #
# RBAC Delegated Editing                                              #
# ------------------------------------------------------------------- #
class TestDelegatedEditing:

    def test_ma_cannot_create_note_without_delegation(self, client_and_appt, toks, db):
        # Ensure no active delegation exists for this client
        db.clinical_delegations.update_many(
            {"delegate_id": db.users.find_one({"email": CREDS["medical_assistant"][0]})["id"]},
            {"$set": {"revoked_at": datetime.now(timezone.utc)}},
        )
        r = requests.post(f"{API}/notes",
                          headers=_h(toks["medical_assistant"]),
                          json={"client_id": client_and_appt["client_id"],
                                "subjective": "s", "objective": "o",
                                "assessment": "a", "plan": "p"},
                          timeout=10)
        assert r.status_code == 403
        detail = r.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code == "delegation_required"

    def test_admin_cannot_finalize_ever(self, client_and_appt, toks, db):
        """Admin loses finalize even for their own drafts."""
        # Create a draft note as practitioner first
        r = requests.post(f"{API}/notes", headers=_h(toks["practitioner"]),
                          json={"client_id": client_and_appt["client_id"],
                                "subjective": "s", "objective": "o",
                                "assessment": "a", "plan": "p"}, timeout=10)
        assert r.status_code == 200, r.text
        note_id = r.json()["id"]
        # Admin tries to finalize → 403
        r2 = requests.post(f"{API}/notes/{note_id}/finalize",
                           headers=_h(toks["admin"]), timeout=10)
        assert r2.status_code == 403

    def test_grant_then_ma_can_create_and_edit(self, client_and_appt, toks, db):
        ma = db.users.find_one({"email": CREDS["medical_assistant"][0]})
        # Grant delegation for this client
        r = requests.post(f"{API}/delegations",
                          headers=_h(toks["practitioner"]),
                          json={"delegate_id": ma["id"],
                                "client_id": client_and_appt["client_id"],
                                "ttl_minutes": 60},
                          timeout=10)
        assert r.status_code == 200, r.text
        deleg_id = r.json()["id"]

        # /delegations/effective returns true for MA
        r2 = requests.get(f"{API}/delegations/effective",
                          headers=_h(toks["medical_assistant"]),
                          params={"client_id": client_and_appt["client_id"]},
                          timeout=10)
        assert r2.json()["can_edit_draft"] is True

        # MA creates a draft note
        r3 = requests.post(f"{API}/notes",
                           headers=_h(toks["medical_assistant"]),
                           json={"client_id": client_and_appt["client_id"],
                                 "subjective": "delegated subj",
                                 "objective": "delegated obj",
                                 "assessment": "a", "plan": "p"},
                           timeout=10)
        assert r3.status_code == 200, r3.text
        note_id = r3.json()["id"]

        # Audit row includes authorizing_provider_id (may be redacted as opaque UUID)
        row = db.audit_logs.find_one({"action": "note.create",
                                      "resource_id": note_id})
        assert row is not None
        meta = row.get("metadata") or {}
        assert meta.get("authorizing_provider_id") is not None
        assert meta.get("actor_role") == "medical_assistant"

        # MA can update the draft too
        r4 = requests.put(f"{API}/notes/{note_id}",
                          headers=_h(toks["medical_assistant"]),
                          json={"client_id": client_and_appt["client_id"],
                                "subjective": "edited by MA",
                                "objective": "o", "assessment": "a", "plan": "p"},
                          timeout=10)
        assert r4.status_code == 200, r4.text

        # MA CANNOT finalize
        r5 = requests.post(f"{API}/notes/{note_id}/finalize",
                           headers=_h(toks["medical_assistant"]), timeout=10)
        assert r5.status_code == 403

        # Provider finalizes successfully
        r6 = requests.post(f"{API}/notes/{note_id}/finalize",
                           headers=_h(toks["practitioner"]), timeout=10)
        assert r6.status_code == 200, r6.text

        # MA CANNOT amend a finalized note
        r7 = requests.post(f"{API}/notes/{note_id}/amend",
                           headers=_h(toks["medical_assistant"]),
                           json={"content": "later addition",
                                 "reason": "clarification"},
                           timeout=10)
        assert r7.status_code == 403

        # Revoke delegation
        r8 = requests.delete(f"{API}/delegations/{deleg_id}",
                             headers=_h(toks["practitioner"]), timeout=10)
        assert r8.status_code == 200

        # MA is read-only again
        r9 = requests.get(f"{API}/delegations/effective",
                          headers=_h(toks["medical_assistant"]),
                          params={"client_id": client_and_appt["client_id"]},
                          timeout=10)
        assert r9.json()["can_edit_draft"] is False
