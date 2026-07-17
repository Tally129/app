"""
Sprint 5+ closure — malware scanning, clinical integrity (treatment plans +
forms), backup/restore verification, startup config validator.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pymongo
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PW = "Admin!2345"


def _login_admin() -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("mfa_required"):
        import pyotp
        code = pyotp.TOTP("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP").now()
        r = s.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PW, "mfa_token": code})
        assert r.status_code == 200
        body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return s


# --------------------------------------------------------------------------- #
# Malware scanning                                                             #
# --------------------------------------------------------------------------- #
def test_clean_upload_marks_scan_status_clean_and_downloads_ok():
    s = _login_admin()
    r = s.post(f"{API}/files/upload",
               files={"file": ("hello.txt", b"totally benign content", "text/plain")})
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["scan_status"] == "clean"
    assert meta.get("scan_engine")
    r = s.get(f"{API}/files/{meta['id']}/download")
    assert r.status_code == 200
    assert r.content == b"totally benign content"


def test_eicar_upload_marks_infected_and_download_blocked():
    s = _login_admin()
    eicar = br"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    r = s.post(f"{API}/files/upload",
               files={"file": ("eicar.txt", eicar, "text/plain")})
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["scan_status"] == "infected"
    r = s.get(f"{API}/files/{meta['id']}/download")
    assert r.status_code == 451
    # And the response body must not disclose the signature name.
    body = r.json()
    assert "Eicar" not in str(body)


# --------------------------------------------------------------------------- #
# Clinical integrity — treatment plans                                         #
# --------------------------------------------------------------------------- #
def test_treatment_plan_finalize_locks_and_amend_requires_finalized():
    s = _login_admin()
    c = s.post(f"{API}/clients", json={
        "full_name": "Plan Patient", "email": f"pp_{uuid.uuid4().hex[:6]}@x.io"}).json()
    r = s.post(f"{API}/treatment-plans", json={
        "client_id": c["id"], "title": "Detox v1", "items": [], "follow_up_days": 30,
    })
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan.get("lifecycle_status") == "draft"
    pid = plan["id"]

    r = s.post(f"{API}/treatment-plans/{pid}/amend",
               json={"content": "should refuse", "reason": "premature"})
    assert r.status_code == 409

    r = s.post(f"{API}/treatment-plans/{pid}/finalize")
    assert r.status_code == 200
    fin = r.json()
    assert fin["lifecycle_status"] == "finalized"
    assert fin.get("prior_versions") and len(fin["prior_versions"]) == 1

    r = s.put(f"{API}/treatment-plans/{pid}",
              json={"client_id": c["id"], "title": "New Title", "items": []})
    assert r.status_code == 409

    r = s.post(f"{API}/treatment-plans/{pid}/amend",
               json={"content": "post-finalize addendum", "reason": "correction"})
    assert r.status_code == 200
    plan = r.json()
    assert plan["amendments"] and plan["amendments"][-1]["reason"] == "correction"


# --------------------------------------------------------------------------- #
# Backup + restore                                                             #
# --------------------------------------------------------------------------- #
def test_backup_and_restore_round_trip():
    # Run the CLI which performs a real mongodump → encrypt → decrypt →
    # mongorestore --dryRun. Fails hard on any step.
    import base64
    env = os.environ.copy()
    env["BACKUP_ENC_KEY_B64"] = base64.b64encode(os.urandom(32)).decode()
    env["MONGO_URL"] = env.get("MONGO_URL", "mongodb://localhost:27017")
    env["DB_NAME"] = env.get("DB_NAME", "test_database")
    p = subprocess.run(
        [sys.executable, "scripts/backup_test.py"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env, capture_output=True, timeout=180,
    )
    assert p.returncode == 0, p.stdout.decode() + p.stderr.decode()
    out = p.stdout.decode()
    assert "BACKUP OK" in out
    assert "RESTORE VERIFY OK" in out
    assert "\"dry_run_restore\": \"ok\"" in out
    assert "\"checksum_ok\": true" in out


# --------------------------------------------------------------------------- #
# Startup validator                                                            #
# --------------------------------------------------------------------------- #
def test_startup_refuses_unsafe_hipaa_config():
    from security_config import UnsafeProductionConfig, enforce_production_config
    orig = os.environ.copy()
    try:
        os.environ["HIPAA_MODE"] = "true"
        os.environ["MALWARE_SCAN_MODE"] = "stub_clean"
        with pytest.raises(UnsafeProductionConfig):
            enforce_production_config()
        os.environ["MALWARE_SCAN_MODE"] = "clamscan"
        os.environ["RATE_LIMIT_TEST_MODE"] = "1"
        with pytest.raises(UnsafeProductionConfig):
            enforce_production_config()
    finally:
        os.environ.clear()
        os.environ.update(orig)


def test_startup_accepts_dev_config():
    from security_config import enforce_production_config
    orig = os.environ.copy()
    try:
        os.environ["HIPAA_MODE"] = "false"
        os.environ["RATE_LIMIT_TEST_MODE"] = "1"
        os.environ["MALWARE_SCAN_MODE"] = "stub_clean"
        enforce_production_config()  # must not raise
    finally:
        os.environ.clear()
        os.environ.update(orig)
