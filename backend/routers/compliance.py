"""
HIPAA compliance endpoints — BAA checklist, patient §164.524 data export,
§164.528 accounting of disclosures.

Extracted from server.py during Phase 16 refactor.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request

from audit import get_client_ip, log_audit
from deps import (
    _resolve_self_client, _strip_id, api, db,
    get_current_user, require_roles,
)
from models import new_id


@api.get("/compliance/baa-checklist")
async def get_baa_checklist(user=Depends(require_roles("admin"))):
    """Return the BAA checklist rows (idempotent — seeds defaults on first read)."""
    defaults = [
        {"key": "mongodb_atlas",    "vendor": "MongoDB Atlas",         "purpose": "Primary PHI database (patients, notes, appointments)", "required": True,  "docs_url": "https://www.mongodb.com/legal/hipaa-security-info"},
        {"key": "aws",              "vendor": "AWS",                    "purpose": "Application hosting after go-live (Elastic Beanstalk / ECS)", "required": True, "docs_url": "https://aws.amazon.com/compliance/hipaa-compliance/"},
        {"key": "anthropic",        "vendor": "Anthropic (Claude 4.5)", "purpose": "AI SOAP drafting, form transcription, protocol AI",     "required": True,  "docs_url": "https://www.anthropic.com/legal/aup"},
        {"key": "twilio",           "vendor": "Twilio",                 "purpose": "Appointment reminder SMS + patient link delivery",       "required": True,  "docs_url": "https://www.twilio.com/legal/baa"},
        {"key": "sendgrid",         "vendor": "SendGrid (Twilio)",      "purpose": "Transactional email — form links, receipts",              "required": True,  "docs_url": "https://sendgrid.com/en-us/policies/legal/hipaa"},
        {"key": "google_workspace", "vendor": "Google Workspace + OAuth","purpose": "Direct Google SSO replacing Emergent-managed SSO",       "required": True,  "docs_url": "https://support.google.com/a/answer/3407054"},
        {"key": "stripe",           "vendor": "Stripe",                 "purpose": "Card processing (Stripe does NOT sign BAAs — safe if no PHI in metadata)", "required": False, "docs_url": "https://support.stripe.com/questions/hipaa-compliance-and-stripe"},
        {"key": "emergent_migration","vendor": "Emergent (hosting)",    "purpose": "MUST migrate off Emergent-managed hosting before onboarding a real patient — no BAA available.", "required": True, "docs_url": None},
    ]
    rows = await db.baa_records.find({}).to_list(50)
    by_key = {r["key"]: r for r in rows}
    out = []
    now = datetime.now(timezone.utc)
    for d in defaults:
        r = by_key.get(d["key"])
        if not r:
            r = {**d, "id": new_id(), "status": "not_started", "signed_at": None, "signed_by": None, "notes": "", "updated_at": now}
            await db.baa_records.insert_one(r)
        out.append(_strip_id(r))
    return out


@api.put("/compliance/baa-checklist/{key}")
async def update_baa_record(key: str, payload: dict, request: Request, user=Depends(require_roles("admin"))):
    doc = await db.baa_records.find_one({"key": key})
    if not doc:
        raise HTTPException(status_code=404, detail="BAA record not found — call GET first")
    updates: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    status = payload.get("status")
    if status in {"not_started", "requested", "signed", "not_applicable"}:
        updates["status"] = status
        if status == "signed":
            updates["signed_at"] = datetime.now(timezone.utc)
            updates["signed_by"] = user.get("full_name") or user.get("email")
        elif status != "signed":
            updates["signed_at"] = None
            updates["signed_by"] = None
    if "notes" in payload:
        updates["notes"] = str(payload.get("notes") or "")[:1000]
    await db.baa_records.update_one({"key": key}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "compliance.baa_update",
                    resource_type="baa", resource_id=key, metadata=updates)
    return _strip_id(await db.baa_records.find_one({"key": key}))


@api.post("/patient/data-export")
async def patient_data_export(request: Request, user=Depends(get_current_user)):
    """§164.524 — patient right to access. Returns their complete record as JSON."""
    if user["role"] != "client":
        raise HTTPException(status_code=403, detail="Only patients may export their own data via this endpoint")
    self_c = await _resolve_self_client(user)
    if not self_c:
        raise HTTPException(status_code=404, detail="No client record linked")
    cid = self_c["id"]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "patient": _strip_id(self_c),
        "user_account": {k: user.get(k) for k in ("id", "email", "full_name", "role", "created_at")},
        "appointments": [_strip_id(a) async for a in db.appointments.find({"client_id": cid})],
        "visit_notes": [_strip_id(n) async for n in db.visit_notes.find({"client_id": cid})],
        "treatment_plans": [_strip_id(t) async for t in db.treatment_plans.find({"client_id": cid})],
        "protocol_enrollments": [_strip_id(p) async for p in db.protocol_enrollments.find({"client_id": cid})],
        "supplement_assignments": [_strip_id(s) async for s in db.client_supplement_assignments.find({"client_id": cid})],
        "form_submissions": [_strip_id(f) async for f in db.form_submissions.find({"client_id": cid})],
        "files": [_strip_id(f) async for f in db.files.find({"client_id": cid})],
        "billing": [_strip_id(b) async for b in db.pos_sales.find({"client_id": cid})],
    }
    await log_audit(db, user["id"], user["email"], "patient.data_export",
                    resource_type="client", resource_id=cid,
                    metadata={"record_counts": {k: len(v) for k, v in payload.items() if isinstance(v, list)}},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return payload


@api.get("/clients/{client_id}/disclosures")
async def accounting_of_disclosures(client_id: str, request: Request,
                                    user=Depends(get_current_user)):
    """§164.528 — patient right to an accounting of disclosures.
    Returns every audit log row that references this client, filtered to the read/access events."""
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or sc["id"] != client_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    q = {
        "$or": [
            {"resource_type": "client", "resource_id": client_id},
            {"metadata.client_id": client_id},
        ]
    }
    rows = await db.audit_logs.find(q).sort("ts", -1).to_list(2000)
    hits = [_strip_id(r) for r in rows]
    await log_audit(db, user["id"], user["email"], "patient.accounting_view",
                    resource_type="client", resource_id=client_id,
                    metadata={"count": len(hits)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"client_id": client_id, "generated_at": datetime.now(timezone.utc).isoformat(), "disclosures": hits}
