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
    from auth_utils import encrypt_mfa_secret  # noqa: WPS433 — deferred import

    c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    dbh = c[os.environ.get("DB_NAME", "test_database")]
    # 1) Enrol MFA on seeded workforce accounts (idempotent). Store as ciphertext.
    dbh.users.update_many(
        {"email": {"$in": list(SEEDED_WORKFORCE)}},
        {"$set": {"mfa_enabled": True, "mfa_secret": encrypt_mfa_secret(FIXTURE_TOTP_SECRET)}},
    )
    # 1b) Sprint 2: clear any active sessions on seeded workforce accounts so the
    #     5-session cap doesn't reject the very first test login.
    user_ids = [u["id"] for u in dbh.users.find(
        {"email": {"$in": list(SEEDED_WORKFORCE)}}, {"id": 1})]
    from datetime import datetime, timezone
    dbh.user_sessions.update_many(
        {"user_id": {"$in": user_ids}, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc), "revoke_reason": "test_setup_cleanup"}},
    )
    dbh.refresh_tokens.update_many(
        {"user_id": {"$in": user_ids}, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc), "revoke_reason": "test_setup_cleanup"}},
    )
    c.close()

    # 2) Monkey-patch requests.post AND requests.Session.post so login for
    # seeded workforce auto-appends TOTP (Sprint 2: cookie-based refresh needs Session).
    _orig_post = requests.post
    _orig_session_post = requests.Session.post

    def _auto_totp(orig_call, url, *args, **kwargs):
        try:
            if isinstance(url, str) and url.endswith("/auth/login"):
                body = kwargs.get("json") or {}
                email = (body.get("email") or "").lower()
                if email in SEEDED_WORKFORCE and not body.get("mfa_token"):
                    resp = orig_call(url, *args, **kwargs)
                    try:
                        j = resp.json()
                    except Exception:
                        return resp
                    if j.get("mfa_required"):
                        totp = pyotp.TOTP(FIXTURE_TOTP_SECRET).now()
                        kwargs["json"] = {**body, "mfa_token": totp}
                        return orig_call(url, *args, **kwargs)
                    return resp
        except Exception:
            pass
        return orig_call(url, *args, **kwargs)

    def _patched_post(url, *args, **kwargs):
        return _auto_totp(_orig_post, url, *args, **kwargs)

    def _patched_session_post(self, url, *args, **kwargs):
        return _auto_totp(lambda u, *a, **kw: _orig_session_post(self, u, *a, **kw),
                          url, *args, **kwargs)

    requests.post = _patched_post
    requests.Session.post = _patched_session_post
    yield
    requests.post = _orig_post
    requests.Session.post = _orig_session_post


@pytest.fixture(autouse=True)
def _ensure_builtin_form_templates():
    """Guarantee the 3 built-in form templates exist before every test.
    Uses upsert-by-title so existing template IDs stay stable across tests."""
    c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    dbh = c[os.environ.get("DB_NAME", "test_database")]
    from datetime import datetime, timezone
    import uuid
    now = datetime.now(timezone.utc)
    for title, desc, cat, fields in [
        ("Treatment Consent",
         "Wellness treatment consent — bodywork, IV therapy, detox protocols.", "consent",
         [
             {"id":"patient-name","type":"text","label":"Patient full name","required":True,"options":[]},
             {"id":"dob","type":"date","label":"Date of birth","required":True,"options":[]},
             {"id":"informed-consent","type":"checkbox","label":"I understand these are wellness treatments.","required":True,"options":[]},
             {"id":"signature","type":"signature","label":"Patient signature","required":True,"options":[]},
         ]),
        ("HIPAA Notice of Privacy Practices",
         "Acknowledgement of our HIPAA privacy practices for your PHI.", "hipaa",
         [
             {"id":"acknowledge","type":"checkbox","label":"I acknowledge receipt of the Notice of Privacy Practices.","required":True,"options":[]},
             {"id":"signature","type":"signature","label":"Patient signature","required":True,"options":[]},
         ]),
        ("Photo & Likeness Release",
         "Consent for before/after photography and use of patient likeness.", "photo_release",
         [
             {"id":"patient-name","type":"text","label":"Patient name","required":True,"options":[]},
             {"id":"signature","type":"signature","label":"Patient signature","required":True,"options":[]},
         ]),
    ]:
        dbh.form_templates.update_one(
            {"title": title, "builtin": True},
            {
                "$setOnInsert": {
                    "id": uuid.uuid4().hex, "created_at": now, "created_by": None,
                    "created_by_name": "Built-in",
                },
                "$set": {
                    "builtin": True, "active": True, "title": title,
                    "description": desc, "category": cat, "fields": fields,
                    "updated_at": now,
                },
            },
            upsert=True,
        )
    c.close()
    yield
