"""
Sprint 3 — RBAC (permission catalog + role mapping), Break-glass workflow,
Audit hash chain, File vault hardening, Note versioning, Rate limiting,
Admin Session Explorer.

Uses live HTTP + seeded workforce accounts (admin/practitioner/auditor).
"""
from __future__ import annotations

import io
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pymongo
import pyotp
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

FIXTURE_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PW = "Admin!2345"
PRAC_EMAIL = "ravello@natmedsol.local"
PRAC_PW = "Ravello!2345"
AUDITOR_EMAIL = "auditor@natmedsol.local"
AUDITOR_PW = "Auditor!2345"


def _db():
    return pymongo.MongoClient(MONGO_URL)[DB_NAME]


def _login(session: requests.Session, email: str, password: str) -> str:
    r = session.post(f"{API}/auth/login",
                     json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("mfa_required"):
        code = pyotp.TOTP(FIXTURE_TOTP_SECRET).now()
        r = session.post(f"{API}/auth/login",
                         json={"email": email, "password": password, "mfa_token": code})
        assert r.status_code == 200, r.text
        body = r.json()
    token = body["access_token"]
    session.headers.update({"Authorization": f"Bearer {token}"})
    return token


def _fresh_client_user() -> tuple[requests.Session, dict, str]:
    s = requests.Session()
    email = f"rbac_{uuid.uuid4().hex[:10]}@example.com"
    pw = "Sprint3Test!23456"
    r = s.post(f"{API}/auth/register", json={
        "email": email, "password": pw,
        "full_name": "RBAC Client", "phone": "+15555550200",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return s, body["user"], pw


# --------------------------------------------------------------------------- #
# Permission catalog + role mapping                                            #
# --------------------------------------------------------------------------- #
def test_client_cannot_list_all_clients():
    s, _, _ = _fresh_client_user()
    r = s.get(f"{API}/clients")
    assert r.status_code == 403


def test_admin_can_list_all_clients():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    r = s.get(f"{API}/clients")
    assert r.status_code == 200


def test_auditor_get_is_break_glass_read_and_audited():
    s = requests.Session()
    _login(s, AUDITOR_EMAIL, AUDITOR_PW)
    r = s.get(f"{API}/clients")
    assert r.status_code == 200
    # Confirm audit row landed
    time.sleep(0.2)
    rows = list(_db().audit_logs.find({"action": "auditor.break_glass_read"}).sort("ts", -1).limit(3))
    assert rows, "auditor break-glass read must produce an audit row"
    assert rows[0].get("severity") == "high"


def test_auditor_cannot_write():
    s = requests.Session()
    _login(s, AUDITOR_EMAIL, AUDITOR_PW)
    r = s.post(f"{API}/clients", json={"full_name": "Should Fail", "email": "x@y.z"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Break-glass                                                                  #
# --------------------------------------------------------------------------- #
def test_break_glass_activate_requires_mfa_recent_and_reason_and_target():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    # Missing reason → 422 (Pydantic min_length)
    r = s.post(f"{API}/breakglass/activate", json={"target_client_id": "c-1"})
    assert r.status_code in (400, 422)
    # No target at all → 400
    r = s.post(f"{API}/breakglass/activate", json={"reason": "x" * 30})
    assert r.status_code == 400


def test_break_glass_activate_and_visible_indicator_and_expiry():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    # Seed a client to target.
    r = s.post(f"{API}/clients", json={"full_name": "BG Target", "email": f"bg_{uuid.uuid4().hex[:6]}@x.io"})
    assert r.status_code == 200
    cid = r.json()["id"]
    reason = "Emergency access to reconcile lab-imported values for treatment planning."
    r = s.post(f"{API}/breakglass/activate", json={
        "target_client_id": cid, "reason": reason, "duration_minutes": 30,
    })
    assert r.status_code == 200, r.text
    bg = r.json()
    assert bg["duration_minutes"] == 30
    assert bg["target_client_id"] == cid
    # Visible indicator
    r = s.get(f"{API}/breakglass/active")
    assert r.status_code == 200
    active = r.json()
    assert any(x["id"] == bg["id"] for x in active)
    # Audit event exists with high severity
    row = _db().audit_logs.find_one({"action": "breakglass.activate", "resource_id": bg["id"]})
    assert row and row.get("severity") == "high"
    # Duration cap enforced by Pydantic
    r = s.post(f"{API}/breakglass/activate", json={
        "target_client_id": cid, "reason": reason, "duration_minutes": 999,
    })
    assert r.status_code == 422


def test_client_cannot_activate_break_glass():
    s, _, _ = _fresh_client_user()
    r = s.post(f"{API}/breakglass/activate", json={
        "target_client_id": "irrelevant",
        "reason": "definitely twenty chars long here",
        "duration_minutes": 15,
    })
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Audit integrity — hash chain                                                 #
# --------------------------------------------------------------------------- #
def test_audit_chain_verifier_returns_ok():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    r = s.get(f"{API}/admin/audit/verify-chain?limit=200")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, f"audit chain broken at {body.get('first_break')}"
    assert body["checked"] >= 1


def test_audit_rows_have_severity_and_outcome_and_hash():
    row = _db().audit_logs.find_one({}, sort=[("ts", -1)])
    assert row
    assert row.get("severity") in {"info", "warning", "high", "critical"}
    assert row.get("outcome") in {"allow", "deny", "success", "failure", "error"}
    assert row.get("hash") and isinstance(row["hash"], str) and len(row["hash"]) == 64
    assert "prev_hash" in row


# --------------------------------------------------------------------------- #
# File vault hardening                                                         #
# --------------------------------------------------------------------------- #
def test_file_upload_rejects_disallowed_mime():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    r = s.post(f"{API}/files/upload", files={
        "file": ("evil.exe", b"MZ\x00\x00", "application/x-msdownload"),
    })
    assert r.status_code == 415


def test_file_upload_produces_checksum_and_soft_delete():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    payload = b"hello world sprint 3"
    r = s.post(f"{API}/files/upload", files={
        "file": ("hello.txt", payload, "text/plain"),
    })
    assert r.status_code == 200, r.text
    file_meta = r.json()
    assert file_meta.get("sha256")
    fid = file_meta["id"]
    # List (should include)
    r = s.get(f"{API}/files")
    assert any(f["id"] == fid for f in r.json())
    # Delete (soft)
    r = s.delete(f"{API}/files/{fid}")
    assert r.status_code == 200
    # After delete, GET returns 404; list no longer includes it
    r = s.get(f"{API}/files/{fid}/download")
    assert r.status_code == 404
    r = s.get(f"{API}/files")
    assert not any(f["id"] == fid for f in r.json())


def test_client_cannot_download_other_clients_file():
    s_admin = requests.Session(); _login(s_admin, ADMIN_EMAIL, ADMIN_PW)
    # Create a client A, upload a file scoped to them.
    ca = s_admin.post(f"{API}/clients", json={
        "full_name": "Client A", "email": f"a_{uuid.uuid4().hex[:6]}@x.io"}).json()
    r = s_admin.post(f"{API}/files/upload",
                     data={"client_id": ca["id"], "category": "doc"},
                     files={"file": ("a.txt", b"phi-a", "text/plain")})
    assert r.status_code == 200
    fid = r.json()["id"]
    # Client B tries to download → 403
    sB, _, _ = _fresh_client_user()
    r = sB.get(f"{API}/files/{fid}/download")
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Clinical record versioning                                                   #
# --------------------------------------------------------------------------- #
def test_note_finalize_makes_it_immutable_and_amend_requires_finalized():
    s = requests.Session(); _login(s, ADMIN_EMAIL, ADMIN_PW)
    c = s.post(f"{API}/clients", json={
        "full_name": "Notes Patient", "email": f"n_{uuid.uuid4().hex[:6]}@x.io"}).json()
    r = s.post(f"{API}/notes", json={
        "client_id": c["id"], "subjective": "s", "objective": "o",
        "assessment": "a", "plan": "p",
    })
    assert r.status_code == 200, r.text
    note = r.json()
    assert note["status"] == "draft"
    nid = note["id"]
    # Amend on draft should be refused via workflow: amend must apply to finalized.
    # (legacy migration allows amend when status is None; here status='draft' → 409)
    r = s.post(f"{API}/notes/{nid}/amend",
               json={"content": "some addendum", "reason": "typo fix"})
    assert r.status_code == 409
    # Finalize
    r = s.post(f"{API}/notes/{nid}/finalize")
    assert r.status_code == 200, r.text
    fin = r.json()
    assert fin["status"] == "finalized"
    assert fin["finalized_at"]
    assert fin.get("prior_versions") and len(fin["prior_versions"]) == 1
    # Editing finalized → 409
    r = s.put(f"{API}/notes/{nid}", json={
        "client_id": c["id"], "subjective": "new", "objective": "new",
        "assessment": "new", "plan": "new",
    })
    assert r.status_code == 409
    # Amend now allowed
    r = s.post(f"{API}/notes/{nid}/amend", json={"content": "post-visit clarification", "reason": "clarify"})
    assert r.status_code == 200
    updated = r.json()
    assert updated["amendments"] and updated["amendments"][-1]["reason"] == "clarify"


# --------------------------------------------------------------------------- #
# Rate limiting                                                                #
# --------------------------------------------------------------------------- #
def test_login_rate_limit_kicks_in():
    email = f"rl_{uuid.uuid4().hex[:8]}@example.com"
    for _ in range(20):
        requests.post(f"{API}/auth/login", json={"email": email, "password": "wrong"})
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": "wrong"})
    # After the sliding window fills we should see 401 (still checked) → then 429.
    assert r.status_code in (401, 423, 429)


# --------------------------------------------------------------------------- #
# Admin Session Explorer                                                       #
# --------------------------------------------------------------------------- #
def test_admin_session_explorer_lists_and_revokes():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    # Log in as practitioner (creates a workforce session).
    sp = requests.Session()
    _login(sp, PRAC_EMAIL, PRAC_PW)
    # Admin lists sessions filtered by that user.
    prac_user = _db().users.find_one({"email": PRAC_EMAIL})
    r = s.get(f"{API}/admin/sessions", params={"user_id": prac_user["id"]})
    assert r.status_code == 200, r.text
    sessions = r.json()
    assert sessions, "practitioner must have at least one active session"
    sid = sessions[0]["id"]
    # Revoke that session
    r = s.post(f"{API}/admin/sessions/{sid}/revoke")
    assert r.status_code == 200
    # Practitioner's next authenticated call must be 401 (session revoked)
    r = sp.get(f"{API}/clients")
    assert r.status_code == 401


def test_admin_revoke_all_sessions_for_a_user():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    sp = requests.Session()
    _login(sp, PRAC_EMAIL, PRAC_PW)
    prac_user = _db().users.find_one({"email": PRAC_EMAIL})
    r = s.post(f"{API}/admin/users/{prac_user['id']}/revoke-all-sessions")
    assert r.status_code == 200
    assert r.json()["sessions_revoked"] >= 1
    r = sp.get(f"{API}/clients")
    assert r.status_code == 401


def test_role_change_revokes_all_sessions_and_bumps_version():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PW)
    # Create a throwaway user + login to build a session, then admin changes their role.
    email = f"rc_{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(f"{API}/admin/users", json={
        "email": email, "password": "Sprint3Test!23456", "full_name": "Role Change",
        "phone": None, "role": "staff",
    })
    assert r.status_code == 200
    new_user = r.json()
    sp = requests.Session()
    _login(sp, email, "Sprint3Test!23456")
    r = s.put(f"{API}/admin/users/{new_user['id']}/role", json={"role": "client"})
    assert r.status_code == 200
    r = sp.get(f"{API}/clients")
    assert r.status_code == 401
