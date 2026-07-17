"""
User-Acceptance Testing — role-based negative + positive workflows.

Complements the sprint1-5 suites by hitting the explicit UAT checkboxes:
  * admin cannot circumvent clinical rules
  * admin cannot see refresh tokens / MFA secrets / passwords
  * practitioner cannot access unassigned client (except break-glass)
  * staff cannot touch clinical
  * auditor is read-only across every write endpoint
  * client cannot access another client's records
  * break-glass complete workflow
  * audit hygiene — no PHI leakage
"""
from __future__ import annotations

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
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
TOTP = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

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
            "email": email, "password": pw, "mfa_token": pyotp.TOTP(TOTP).now()})
        assert r.status_code == 200
        body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return s


def _register_client() -> tuple[requests.Session, dict]:
    s = requests.Session()
    email = f"uat_{uuid.uuid4().hex[:10]}@example.com"
    r = s.post(f"{API}/auth/register", json={
        "email": email, "password": "UatTest!23456",
        "full_name": "UAT Client", "phone": "+15555550300",
    })
    assert r.status_code == 200
    body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return s, body["user"]


# --------------------------------------------------------------------------- #
# ADMIN — negative tests                                                       #
# --------------------------------------------------------------------------- #
def test_admin_cannot_read_mfa_secret_or_password_hash_via_api():
    s = _login(*ADMIN)
    # List users. If our API exposes users, ensure no sensitive fields leak.
    for path in ("/admin/users", "/admin/sessions"):
        r = s.get(f"{API}{path}")
        assert r.status_code in (200, 404), r.text
        body_text = r.text.lower()
        # Never expose bcrypt hashes, MFA secrets, refresh cookie values, tokens.
        forbidden = ["password_hash", "mfa_secret", "refresh_token", "$2b$"]
        leaks = [f for f in forbidden if f in body_text]
        assert not leaks, f"{path} leaked {leaks}"


def test_admin_cannot_edit_finalized_note_via_general_update():
    s = _login(*ADMIN)
    c = s.post(f"{API}/clients", json={
        "full_name": "Finalize Guard", "email": f"fg_{uuid.uuid4().hex[:6]}@x.io"}).json()
    n = s.post(f"{API}/notes", json={
        "client_id": c["id"], "subjective": "s", "objective": "o",
        "assessment": "a", "plan": "p"}).json()
    assert s.post(f"{API}/notes/{n['id']}/finalize").status_code == 200
    r = s.put(f"{API}/notes/{n['id']}", json={
        "client_id": c["id"], "subjective": "tampered", "objective": "o",
        "assessment": "a", "plan": "p"})
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# PRACTITIONER — assigned-only scope + amendment flow                          #
# --------------------------------------------------------------------------- #
def test_practitioner_cannot_access_unassigned_client_without_breakglass():
    admin = _login(*ADMIN)
    prac = _login(*PRAC)
    # Create a client with NO assigned practitioner.
    c = admin.post(f"{API}/clients", json={
        "full_name": "Unassigned Patient",
        "email": f"un_{uuid.uuid4().hex[:6]}@x.io"}).json()
    r = prac.get(f"{API}/clients/{c['id']}")
    # Practitioner without break-glass and without assignment must not access.
    assert r.status_code in (403, 404), r.text


def test_practitioner_can_amend_finalized_note_prior_version_preserved():
    prac = _login(*PRAC)
    # Assign this practitioner to a new client so scope is satisfied.
    admin = _login(*ADMIN)
    prac_user = _db().users.find_one({"email": PRAC[0]})
    c = admin.post(f"{API}/clients", json={
        "full_name": "Amend Patient",
        "email": f"ap_{uuid.uuid4().hex[:6]}@x.io",
        "assigned_practitioner_id": prac_user["id"],
    }).json()
    n = prac.post(f"{API}/notes", json={
        "client_id": c["id"], "subjective": "s1", "objective": "o1",
        "assessment": "a1", "plan": "p1"}).json()
    prac.post(f"{API}/notes/{n['id']}/finalize")
    r = prac.post(f"{API}/notes/{n['id']}/amend",
                  json={"content": "clarify diagnosis", "reason": "post-visit correction"})
    assert r.status_code == 200
    final = r.json()
    # prior_versions[0].subjective must still equal "s1" (immutable)
    assert final["prior_versions"][0]["subjective"] == "s1"


# --------------------------------------------------------------------------- #
# STAFF — cannot touch clinical                                                #
# --------------------------------------------------------------------------- #
def test_staff_cannot_create_or_amend_soap_note():
    # Create a staff user via admin
    admin = _login(*ADMIN)
    email = f"staff_{uuid.uuid4().hex[:8]}@example.com"
    admin.post(f"{API}/admin/users", json={
        "email": email, "password": "UatTest!23456",
        "full_name": "UAT Staff", "phone": None, "role": "staff"})
    staff = _login(email, "UatTest!23456")
    r = staff.post(f"{API}/notes", json={
        "client_id": "does-not-matter", "subjective": "x", "objective": "x",
        "assessment": "x", "plan": "x"})
    assert r.status_code == 403


def test_staff_cannot_activate_break_glass():
    admin = _login(*ADMIN)
    email = f"staff_{uuid.uuid4().hex[:8]}@example.com"
    admin.post(f"{API}/admin/users", json={
        "email": email, "password": "UatTest!23456",
        "full_name": "UAT Staff2", "phone": None, "role": "staff"})
    staff = _login(email, "UatTest!23456")
    r = staff.post(f"{API}/breakglass/activate", json={
        "target_client_id": "irrelevant",
        "reason": "very legitimate emergency reason here",
        "duration_minutes": 15,
    })
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# AUDITOR — read-only across every write endpoint                              #
# --------------------------------------------------------------------------- #
def test_auditor_cannot_write_across_all_endpoints():
    s = _login(*AUDITOR)
    writes = [
        ("POST", "/clients", {"full_name": "x", "email": "x@x.x"}),
        ("POST", "/notes", {"client_id": "x", "subjective": "x", "objective": "x",
                            "assessment": "x", "plan": "x"}),
        ("POST", "/treatment-plans", {"client_id": "x", "title": "x", "items": []}),
        ("POST", "/files/upload", None),  # multipart
        ("POST", "/breakglass/activate", {"reason": "a" * 30,
                                          "target_client_id": "x",
                                          "duration_minutes": 15}),
        ("PUT", "/admin/users/xxx/role", {"role": "client"}),
    ]
    for method, path, body in writes:
        if body is None:
            r = s.post(f"{API}{path}",
                       files={"file": ("x.txt", b"x", "text/plain")})
        elif method == "POST":
            r = s.post(f"{API}{path}", json=body)
        else:
            r = s.put(f"{API}{path}", json=body)
        assert r.status_code in (403, 405), f"{method} {path} unexpectedly {r.status_code}: {r.text[:120]}"


# --------------------------------------------------------------------------- #
# CLIENT — cannot escalate                                                     #
# --------------------------------------------------------------------------- #
def test_client_cannot_read_other_client_via_id():
    s_admin = _login(*ADMIN)
    other = s_admin.post(f"{API}/clients", json={
        "full_name": "Other", "email": f"o_{uuid.uuid4().hex[:6]}@x.io"}).json()
    sB, _ = _register_client()
    r = sB.get(f"{API}/clients/{other['id']}")
    assert r.status_code in (403, 404)


def test_client_cannot_reach_admin_or_audit():
    sB, _ = _register_client()
    for path in ("/admin/users", "/admin/sessions", "/admin/audit/verify-chain",
                 "/admin/audit-logs", "/breakglass/active"):
        r = sB.get(f"{API}{path}")
        assert r.status_code in (401, 403, 404), f"client reached {path}: {r.status_code}"


# --------------------------------------------------------------------------- #
# Break-glass complete workflow                                                #
# --------------------------------------------------------------------------- #
def test_break_glass_expiry_denies_further_access():
    admin = _login(*ADMIN)
    c = admin.post(f"{API}/clients", json={
        "full_name": "BG Expire", "email": f"bge_{uuid.uuid4().hex[:6]}@x.io"}).json()
    r = admin.post(f"{API}/breakglass/activate", json={
        "target_client_id": c["id"], "duration_minutes": 1,
        "reason": "emergency reconciliation for lab imports"})
    assert r.status_code == 200
    bg = r.json()
    # Force expiry directly in DB (avoid a 60s sleep in CI).
    _db().breakglass_sessions.update_one(
        {"id": bg["id"]},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=5)}},
    )
    r = admin.get(f"{API}/breakglass/active")
    active_ids = [x["id"] for x in r.json()]
    assert bg["id"] not in active_ids, "expired break-glass should not appear in active list"


# --------------------------------------------------------------------------- #
# Session security                                                             #
# --------------------------------------------------------------------------- #
def test_logout_all_revokes_all_sessions():
    s1 = _login(*ADMIN)
    s2 = _login(*ADMIN)
    r = s1.post(f"{API}/auth/logout-all")
    assert r.status_code == 200
    r = s2.get(f"{API}/auth/me")
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Audit hygiene — no PHI / secrets in log rows                                 #
# --------------------------------------------------------------------------- #
def test_audit_rows_never_carry_forbidden_fields():
    forbidden = {"password", "password_hash", "mfa_secret",
                 "refresh_token", "cookie", "otp"}
    rows = list(_db().audit_logs.find({}, {"metadata": 1}).limit(2000))
    for r in rows:
        meta = r.get("metadata") or {}
        keys = {k.lower() for k in meta.keys()}
        # Redacted values are allowed but keys with these names should already
        # be scrubbed to "[REDACTED]" by audit._redact.
        leaks = keys & forbidden
        for k in leaks:
            assert str(meta[k]).startswith("[REDACTED"), \
                f"audit metadata leaked plaintext '{k}': {meta[k]!r}"


# --------------------------------------------------------------------------- #
# File security matrix                                                         #
# --------------------------------------------------------------------------- #
def test_file_pending_scan_download_returns_425():
    """Simulate a pending-scan file by injecting a scan_status=pending row."""
    admin = _login(*ADMIN)
    r = admin.post(f"{API}/files/upload",
                   files={"file": ("pending.txt", b"stub", "text/plain")})
    fid = r.json()["id"]
    _db().files.update_one({"id": fid}, {"$set": {"scan_status": "pending"}})
    r = admin.get(f"{API}/files/{fid}/download")
    assert r.status_code == 425


def test_file_error_scan_download_returns_503():
    admin = _login(*ADMIN)
    r = admin.post(f"{API}/files/upload",
                   files={"file": ("err.txt", b"stub", "text/plain")})
    fid = r.json()["id"]
    _db().files.update_one({"id": fid}, {"$set": {"scan_status": "error"}})
    r = admin.get(f"{API}/files/{fid}/download")
    assert r.status_code == 503
