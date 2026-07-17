"""
Shared pytest configuration.

Sprint 1 enforces workforce MFA on every PHI endpoint. Pre-existing tests
authenticate as the seeded workforce accounts without knowing anything about
MFA. To keep those tests running without touching each file:

  1. At session start, we DB-write `mfa_enabled=True` + a KNOWN base32 secret
     onto the 5 seeded workforce accounts.
  2. We monkey-patch `requests.post` so that any POST to `/api/auth/login`
     targeting one of those seeded emails is automatically resubmitted with a
     freshly computed TOTP `mfa_token` after the initial `mfa_required: True`
     response.

This is safe because it only activates for the seeded fixture emails. Fresh
accounts created by individual tests still exercise the real MFA flow.
"""
from __future__ import annotations

import os

import pymongo
import pyotp
import pytest
import requests

SEEDED_WORKFORCE = {
    "tallyravello@gmail.com",
    "admin@natmedsol.local",
    "ravello@natmedsol.local",
    "frontdesk@natmedsol.local",
    "auditor@natmedsol.local",
}
# 32-char base32 — deterministic so tests can compute the TOTP.
FIXTURE_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


@pytest.fixture(scope="session", autouse=True)
def _enroll_workforce_mfa_and_patch_login():
    c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    dbh = c[os.environ.get("DB_NAME", "test_database")]
    # 1) Enrol MFA on seeded workforce accounts (idempotent).
    dbh.users.update_many(
        {"email": {"$in": list(SEEDED_WORKFORCE)}},
        {"$set": {"mfa_enabled": True, "mfa_secret": FIXTURE_TOTP_SECRET}},
    )
    c.close()

    # 2) Monkey-patch requests.post so login for seeded workforce auto-appends TOTP.
    _orig_post = requests.post

    def _patched_post(url, *args, **kwargs):
        try:
            if url.endswith("/auth/login") or url.endswith("/api/auth/login"):
                body = kwargs.get("json") or {}
                email = (body.get("email") or "").lower()
                if email in SEEDED_WORKFORCE and not body.get("mfa_token"):
                    # First submit — if server returns mfa_required, resubmit with TOTP.
                    resp = _orig_post(url, *args, **kwargs)
                    try:
                        j = resp.json()
                    except Exception:
                        return resp
                    if j.get("mfa_required"):
                        totp = pyotp.TOTP(FIXTURE_TOTP_SECRET).now()
                        kwargs["json"] = {**body, "mfa_token": totp}
                        return _orig_post(url, *args, **kwargs)
                    return resp
        except Exception:
            pass
        return _orig_post(url, *args, **kwargs)

    requests.post = _patched_post
    yield
    requests.post = _orig_post
