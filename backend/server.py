"""
NatMedSol EMR — FastAPI application entrypoint.

Route handlers now live in `/app/backend/routers/*.py`. This file wires
FastAPI middleware, the seed/startup jobs, and mounts the shared router.
"""
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Request, Query
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from bson import ObjectId
import os
import io
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from models import (
    UserCreate, UserOut, LoginIn, TokenOut, RefreshIn, MfaVerifyIn,
    ClientIn, ClientOut,
    IntakeIn, IntakeOut,
    NoteIn, NoteOut, AmendIn,
    FileMetaOut,
    AppointmentRequestIn, VipSignupIn,
    AuditLogOut,
    AppointmentIn, AppointmentUpdate, AppointmentOut,
    AvailabilityIn, AvailabilityOut,
    MembershipIn, MembershipOut,
    InvoiceIn, InvoiceOut, MarkPaidIn,
    PlanIn, PlanOut,
    ReminderSettings,
    SymptomLogIn, SymptomLogOut,
    LabValueIn, LabValueOut,
    ThreadIn, ThreadOut, MessageIn, MessageOut,
    TelehealthConsentIn,
    TreatmentIn, TreatmentOut,
    InventoryItemIn, InventoryItemOut, InventoryAdjustIn,
    PosCheckoutIn, TransactionOut,
    TimeEntryOut, TimeEditIn,
    FrontDeskCheckIn, FrontDeskUpdate, FrontDeskOut,
    ProfileUpdate, PasswordChange,
    FormTemplateIn, FormTemplateOut, FormTranscribeOut, FormGenerateIn,
    FormSendIn, FormSubmissionAnswers, FormSubmissionOut, FormPublicOut,
    SoapTemplateIn, SoapTemplateOut,
    ProtocolTemplateIn, ProtocolTemplateOut,
    ProtocolEnrollmentIn, ProtocolEnrollmentOut, ProtocolSessionUpdate, ProtocolDecisionIn,
    new_id,
)
import httpx
import csv
import io as _io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.units import inch
from auth_utils import (
    hash_password, verify_password, validate_password_strength,
    make_access_token, make_refresh_token, decode_token,
    generate_mfa_secret, mfa_provisioning_uri, verify_mfa,
)
from audit import log_audit, get_client_ip

# Shared singletons (mongo, api router, auth helpers) live in deps.py
from deps import (
    api, db, fs_bucket, bearer, logger,
    _strip_id, get_current_user, require_roles, to_user_out, _resolve_self_client,
    close_mongo,
)

# Register modular routers (side-effect: each file adds routes to `api`)
from routers import auth as _auth_routes  # noqa: F401
from routers import clients as _clients_routes  # noqa: F401
from routers import admin as _admin_routes  # noqa: F401
from routers import appointments as _appointments_routes  # noqa: F401
from routers import health_track as _health_track_routes  # noqa: F401
from routers import ops as _ops_routes  # noqa: F401
from routers import telehealth as _telehealth_routes  # noqa: F401
from routers import forms_protocols as _forms_protocols_routes  # noqa: F401
from routers import compliance as _compliance_routes  # noqa: F401
from routers import breakglass as _breakglass_routes  # noqa: F401

# Startup config safety validation (fail-fast in HIPAA_MODE)
from security_config import enforce_production_config
enforce_production_config()


app = FastAPI(title="NatMedSol EMR API")






# =================== PUBLIC ENDPOINTS ===================
@api.post("/public/appointment-request")
async def public_appointment_request(payload: AppointmentRequestIn, request: Request):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["created_at"] = datetime.now(timezone.utc)
    doc["status"] = "new"
    doc["ip"] = get_client_ip(request)
    await db.appointment_requests.insert_one(doc)
    logger.info("[SENDGRID STUB] Would email staff about new appointment request from %s", payload.fullName)
    await db.integration_log.insert_one({
        "id": new_id(), "service": "sendgrid", "action": "appointment_request_notification",
        "payload": {"to": payload.email, "name": payload.fullName},
        "_stubbed": True, "ts": datetime.now(timezone.utc),
    })
    return {"ok": True, "id": doc["id"]}


@api.post("/public/vip-signup")
async def public_vip_signup(payload: VipSignupIn, request: Request):
    doc = {
        "id": new_id(), "email": payload.email.lower(),
        "created_at": datetime.now(timezone.utc), "ip": get_client_ip(request),
    }
    await db.vip_list.insert_one(doc)
    logger.info("[SENDGRID STUB] Would send VIP welcome to %s", payload.email)
    await db.integration_log.insert_one({
        "id": new_id(), "service": "sendgrid", "action": "vip_welcome",
        "payload": {"to": payload.email}, "_stubbed": True,
        "ts": datetime.now(timezone.utc),
    })
    return {"ok": True}


# =================== HEALTH ===================
@api.get("/")
async def root():
    return {"service": "NatMedSol EMR", "status": "ok"}


@api.get("/health")
async def health():
    """Return app + integration status so admins can see which BAAs are wired live."""
    import llm_client
    import notifiers
    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "integrations": {
            "llm": llm_client.provider(),
            "email": notifiers.email_status(),
            "sms": notifiers.sms_status(),
            "google_oauth_direct": bool(
                os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
                and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
                and os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
            ),
        },
    }



# ---------- Recurring appointments ----------
@api.post("/appointments/{appt_id}/recurrence")
async def set_recurrence(appt_id: str, payload: dict,
                          user=Depends(require_roles("practitioner", "admin", "staff"))):
    """Generate a recurring series. Body: {pattern: 'weekly'|'biweekly'|'monthly', count: int}"""
    pattern = payload.get("pattern", "weekly")
    count = max(1, min(int(payload.get("count", 4)), 26))
    parent = await db.appointments.find_one({"id": appt_id})
    if not parent:
        raise HTTPException(status_code=404, detail="Appointment not found")
    series_id = parent.get("series_id") or new_id()
    await db.appointments.update_one({"id": appt_id}, {"$set": {"series_id": series_id, "series_pattern": pattern}})

    delta_days = {"weekly": 7, "biweekly": 14}.get(pattern)
    use_months = pattern == "monthly"
    created = []
    base_start = parent["start"]
    base_end = parent["end"]
    for i in range(1, count + 1):
        if use_months:
            try:
                from dateutil.relativedelta import relativedelta
                new_start = base_start + relativedelta(months=i)
                new_end = base_end + relativedelta(months=i)
            except ImportError:
                new_start = base_start + timedelta(days=30 * i)
                new_end = base_end + timedelta(days=30 * i)
        else:
            new_start = base_start + timedelta(days=delta_days * i)
            new_end = base_end + timedelta(days=delta_days * i)
        doc = {**{k: v for k, v in parent.items() if k != "_id"},
               "id": new_id(),
               "start": new_start, "end": new_end,
               "series_id": series_id,
               "series_pattern": pattern,
               "status": "scheduled",
               "created_at": datetime.now(timezone.utc)}
        await db.appointments.insert_one(doc)
        created.append(doc["id"])
    await log_audit(db, user["id"], user["email"], "appointment.recurrence",
                    resource_type="appointment", resource_id=appt_id,
                    metadata={"pattern": pattern, "count": count, "series_id": series_id})
    return {"series_id": series_id, "created": created, "pattern": pattern}


@api.delete("/appointments/series/{series_id}")
async def cancel_series(series_id: str,
                         user=Depends(require_roles("practitioner", "admin", "staff"))):
    """Cancel all FUTURE appointments in a series."""
    now = datetime.now(timezone.utc)
    res = await db.appointments.update_many(
        {"series_id": series_id, "start": {"$gte": now}, "status": {"$ne": "completed"}},
        {"$set": {"status": "canceled"}},
    )
    return {"cancelled": res.modified_count}


# ---------- Inventory lots / expiration ----------
@api.post("/inventory/{item_id}/lots")
async def add_inventory_lot(item_id: str, payload: dict,
                             user=Depends(require_roles("admin", "staff"))):
    item = await db.inventory_items.find_one({"id": item_id})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    lot = {
        "id": new_id(),
        "lot_number": payload.get("lot_number", ""),
        "qty": int(payload.get("qty", 0)),
        "expires_on": payload.get("expires_on"),  # ISO date string
        "received_on": payload.get("received_on", datetime.now(timezone.utc).isoformat()),
        "note": payload.get("note", ""),
    }
    await db.inventory_items.update_one(
        {"id": item_id},
        {"$push": {"lots": lot}, "$inc": {"stock": lot["qty"]}},
    )
    await log_audit(db, user["id"], user["email"], "inventory.lot_add",
                    resource_type="inventory_item", resource_id=item_id,
                    metadata={"lot": lot})
    return lot


@api.get("/inventory/expiring")
async def list_expiring(days: int = 60,
                         user=Depends(require_roles("admin", "staff", "practitioner"))):
    """Items with at least one lot expiring within `days`."""
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
    items = await db.inventory_items.find({}).to_list(500)
    out = []
    for it in items:
        for lot in it.get("lots", []) or []:
            if lot.get("expires_on") and lot["expires_on"] <= cutoff:
                out.append({**_strip_id(it), "expiring_lot": lot})
                break
    return out


# ---------- Web push (VAPID) ----------
@api.get("/push/public-key")
async def push_public_key():
    return {"public_key": os.environ.get("VAPID_PUBLIC_KEY", "")}


@api.post("/push/subscribe")
async def push_subscribe(payload: dict, user=Depends(get_current_user)):
    sub = payload.get("subscription") or payload  # accept either shape
    if not sub.get("endpoint"):
        raise HTTPException(status_code=400, detail="Missing subscription endpoint")
    await db.push_subscriptions.update_one(
        {"user_id": user["id"], "endpoint": sub["endpoint"]},
        {"$set": {
            "user_id": user["id"], "endpoint": sub["endpoint"],
            "keys": sub.get("keys", {}),
            "updated_at": datetime.now(timezone.utc),
        }, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {"ok": True}


@api.post("/push/unsubscribe")
async def push_unsubscribe(payload: dict, user=Depends(get_current_user)):
    endpoint = payload.get("endpoint")
    if endpoint:
        await db.push_subscriptions.delete_one({"user_id": user["id"], "endpoint": endpoint})
    return {"ok": True}


# ---------- Push broadcast helper ----------
from notifiers import push_to_user  # re-exported for legacy callers


# ---------- Background scheduler: appointment reminders ----------
import asyncio as _asyncio

async def _appointment_reminder_loop():
    """Fires every 5 minutes, sends a push to clients ~1 hour before their appointment.
    Uses a `reminder_sent_at` flag so each appointment is reminded once."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            window_start = now + timedelta(minutes=55)
            window_end = now + timedelta(minutes=65)
            cursor = db.appointments.find({
                "start": {"$gte": window_start, "$lte": window_end},
                "status": {"$in": ["scheduled", "confirmed", "requested"]},
                "reminder_sent_at": {"$exists": False},
            })
            async for a in cursor:
                client = await db.clients.find_one({"id": a.get("client_id")})
                if not client or not client.get("user_id"):
                    continue
                start_local = a["start"].strftime("%-I:%M %p")
                mode = "Telehealth" if a.get("visit_mode") == "telehealth" else "In clinic"
                url = f"/portal/visit/{a['id']}" if a.get("visit_mode") == "telehealth" else "/portal/patient/appointments"
                await push_to_user(
                    client["user_id"],
                    "Appointment in 1 hour",
                    f"{mode} visit at {start_local}",
                    url=url, tag=f"appt-{a['id']}",
                )
                await db.appointments.update_one(
                    {"id": a["id"]},
                    {"$set": {"reminder_sent_at": now}},
                )
        except Exception as e:
            logger.warning("reminder loop tick failed: %s", e)
        await _asyncio.sleep(300)  # 5 min


async def _expiring_inventory_loop():
    """Once per day, push admins about lots expiring within 30 days."""
    while True:
        try:
            cutoff = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
            items = await db.inventory_items.find({}).to_list(500)
            expiring = []
            for it in items:
                for lot in it.get("lots", []) or []:
                    if lot.get("expires_on") and lot["expires_on"] <= cutoff:
                        expiring.append(it["name"])
                        break
            if expiring:
                admins = await db.users.find({"role": {"$in": ["admin", "staff"]}}).to_list(50)
                for u in admins:
                    await push_to_user(
                        u["id"],
                        f"{len(expiring)} inventory item(s) expiring soon",
                        ", ".join(expiring[:3]) + ("…" if len(expiring) > 3 else ""),
                        url="/portal/admin/inventory", tag="inv-expiring",
                    )
        except Exception as e:
            logger.warning("expiring loop tick failed: %s", e)
        await _asyncio.sleep(60 * 60 * 24)  # daily


# ---------- Emergent-managed Google SSO ----------



# =================== STARTUP ===================


# --------- HIPAA hardening (Phase 15) ---------



# --------- HSTS + security headers middleware ---------


@app.middleware("http")
async def hipaa_security_headers(request: Request, call_next):
    # HTTPS enforcement — in HIPAA mode we refuse plaintext HTTP. Behind the
    # ingress the scheme comes from X-Forwarded-Proto; fall back to url.scheme.
    _hipaa = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}
    if _hipaa:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        if proto and proto != "https":
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "HTTPS required"}, status_code=400)
    resp = await call_next(request)
    # HSTS — force HTTPS for 1 year, include subdomains
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(self), camera=(self)"
    # Content-Security-Policy — narrowed for a same-origin SPA. Frontend uses
    # inline styles from tailwind + CRA runtime, so 'unsafe-inline' style/script
    # is retained for now; tighten once bundler emits nonces.
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob: https:; "
        "media-src 'self' blob:; "
        "connect-src 'self' https: wss:; "
        "font-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return resp

@app.on_event("startup")
async def seed_demo():
    # Sprint 1: In HIPAA_MODE=on, refuse to seed predictable staff credentials.
    _hipaa = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}
    try:
        await db.users.create_index("email", unique=True)
        await db.clients.create_index("user_id")
        await db.intake_forms.create_index("client_id", unique=True)
        await db.visit_notes.create_index("client_id")
        await db.files.create_index("client_id")
        await db.audit_logs.create_index("ts")
        await db.ws_tickets.create_index("expires_at", expireAfterSeconds=0)
        await db.push_subscriptions.create_index([("user_id", 1), ("endpoint", 1)], unique=True)
        await db.form_templates.create_index([("builtin", 1), ("title", 1)])
        await db.form_submissions.create_index("token", unique=True)
        await db.form_submissions.create_index("client_id")
        await db.soap_templates.create_index("title")
        await db.protocol_templates.create_index([("builtin", 1), ("title", 1)])
        await db.protocol_enrollments.create_index("client_id")
        await db.protocol_enrollments.create_index("practitioner_id")
        await db.client_supplement_assignments.create_index([("client_id", 1), ("active", 1)])
        await db.client_supplement_assignments.create_index([("client_id", 1), ("sheet_id", 1)], unique=False)
        await db.protocol_enrollments.create_index("status")
        # Sprint 3+ collections
        await db.audit_logs.create_index([("ts", 1)])
        await db.audit_logs.create_index("action")
        await db.audit_logs.create_index("severity")
        await db.security_events.create_index([("ts", -1)])
        await db.security_events.create_index("handled")
        await db.breakglass_sessions.create_index("user_id")
        await db.breakglass_sessions.create_index("expires_at")
        await db.breakglass_sessions.create_index("target_client_id")
        await db.files.create_index("deleted_at")
        await db.visit_notes.create_index("status")
    except Exception as e:
        logger.warning("Index creation warning: %s", e)

    # Background tasks for push triggers
    _asyncio.create_task(_appointment_reminder_loop())
    _asyncio.create_task(_expiring_inventory_loop())

    if _hipaa:
        # HIPAA mode: refuse to seed predictable staff credentials. Migration script
        # (scripts/sprint1_migration.py) also blocks startup when they persist.
        logger.warning("HIPAA_MODE=on — skipping predictable-password demo seed.")
        return

    if await db.users.count_documents({}) == 0:
        admin = {
            "id": new_id(), "email": "admin@natmedsol.local",
            "password_hash": hash_password("Admin!2345"),
            "full_name": "Site Administrator", "phone": None,
            "role": "admin", "mfa_enabled": False, "mfa_secret": None,
            "is_active": True, "created_at": datetime.now(timezone.utc), "last_login_at": None,
        }
        prac = {
            "id": new_id(), "email": "ravello@natmedsol.local",
            "password_hash": hash_password("Ravello!2345"),
            "full_name": "Dr. Gail Ravello", "phone": None,
            "role": "practitioner", "mfa_enabled": False, "mfa_secret": None,
            "is_active": True, "created_at": datetime.now(timezone.utc), "last_login_at": None,
        }
        await db.users.insert_many([admin, prac])
        logger.info("Seeded demo admin + practitioner users.")

    # Idempotent: ensure a real staff-role front-desk user exists for QA / RBAC testing
    if not await db.users.find_one({"email": "frontdesk@natmedsol.local"}):
        await db.users.insert_one({
            "id": new_id(), "email": "frontdesk@natmedsol.local",
            "password_hash": hash_password("FrontDesk!2345"),
            "full_name": "Front Desk Staff", "phone": None,
            "role": "staff", "mfa_enabled": False, "mfa_secret": None,
            "is_active": True, "created_at": datetime.now(timezone.utc), "last_login_at": None,
        })
        logger.info("Seeded demo staff (front desk) user.")

    # Idempotent break-glass auditor account (read-only, all reads stamped emergency=true)
    if not await db.users.find_one({"email": "auditor@natmedsol.local"}):
        await db.users.insert_one({
            "id": new_id(), "email": "auditor@natmedsol.local",
            "password_hash": hash_password("Auditor!2345"),
            "full_name": "Compliance Auditor", "phone": None,
            "role": "auditor", "mfa_enabled": False, "mfa_secret": None,
            "is_active": True, "created_at": datetime.now(timezone.utc), "last_login_at": None,
        })
        logger.info("Seeded break-glass auditor user.")

    # Idempotent: ensure 3 built-in form templates exist (Phase 10)
    builtins = [
        {
            "title": "Treatment Consent",
            "description": "General consent to receive wellness treatment services at Natural Medical Solutions.",
            "category": "treatment",
            "fields": [
                {"id": "patient-name", "type": "text", "label": "Patient name", "required": True, "options": [], "placeholder": None, "help_text": None},
                {"id": "dob", "type": "date", "label": "Date of birth", "required": True, "options": [], "placeholder": None, "help_text": None},
                {"id": "concern", "type": "textarea", "label": "Primary concern or reason for visit", "required": False, "options": [], "placeholder": None, "help_text": None},
                {"id": "allergies", "type": "textarea", "label": "Known allergies / sensitivities", "required": False, "options": [], "placeholder": None, "help_text": None},
                {"id": "informed-consent", "type": "checkbox", "label": "I understand the treatments offered are wellness-focused and not intended to diagnose, treat, or cure disease.", "required": True, "options": [], "placeholder": None, "help_text": None},
                {"id": "consent-date", "type": "date", "label": "Date", "required": True, "options": [], "placeholder": None, "help_text": None},
                {"id": "signature", "type": "signature", "label": "Patient signature", "required": True, "options": [], "placeholder": None, "help_text": None},
            ],
        },
        {
            "title": "HIPAA Notice of Privacy Practices",
            "description": "Acknowledgement of our HIPAA privacy practices for your protected health information.",
            "category": "hipaa",
            "fields": [
                {"id": "acknowledge", "type": "checkbox", "label": "I acknowledge that I have received the Notice of Privacy Practices.", "required": True, "options": [], "placeholder": None, "help_text": None},
                {"id": "signature", "type": "signature", "label": "Patient signature", "required": True, "options": [], "placeholder": None, "help_text": None},
            ],
        },
        {
            "title": "Photo & Likeness Release",
            "description": "Consent for before/after photography and permitted use of patient likeness.",
            "category": "photo_release",
            "fields": [
                {"id": "patient-name", "type": "text", "label": "Patient name", "required": True, "options": [], "placeholder": None, "help_text": None},
                {"id": "use-options", "type": "radio", "label": "Permitted use",
                 "required": True,
                 "options": ["Internal records only", "Internal + provider review", "Internal + marketing (with face redacted)", "Full marketing release (face visible)"],
                 "placeholder": None, "help_text": None},
                {"id": "consent-date", "type": "date", "label": "Date", "required": True, "options": [], "placeholder": None, "help_text": None},
                {"id": "signature", "type": "signature", "label": "Patient signature", "required": True, "options": [], "placeholder": None, "help_text": None},
            ],
        },
    ]
    now = datetime.now(timezone.utc)
    for b in builtins:
        if not await db.form_templates.find_one({"title": b["title"], "builtin": True}):
            await db.form_templates.insert_one({
                "id": new_id(),
                "builtin": True,
                "active": True,
                "created_by": None,
                "created_by_name": "Built-in",
                "created_at": now,
                "updated_at": now,
                **b,
            })
            logger.info("Seeded built-in form template: %s", b["title"])

    # Idempotent SOAP starter templates
    soap_seeds = [
        {
            "title": "General wellness follow-up",
            "description": "Standard follow-up visit template covering progress, vitals, plan refresh.",
            "subjective": "Client reports … Sleep: …  Energy: …  Mood: …  Appetite: …  Bowel/digestion: …",
            "objective": "Vitals (if taken): BP …, HR …, Wt …  Observed: …",
            "assessment": "Progress on previously identified concerns. Trending: …",
            "plan": "1. Continue current supplements\n2. Lifestyle: …\n3. Labs to repeat: …\n4. Follow-up in __ weeks.",
            "visit_type": None,
            "active": True,
        },
        {
            "title": "Telehealth check-in",
            "description": "Brief telehealth visit template — focuses on reported symptoms, no in-person vitals.",
            "subjective": "Reason for today's call: …  Since last visit: …  Concerns: …",
            "objective": "Visual exam (telehealth): general appearance, skin tone, affect.",
            "assessment": "Updated impression based on subjective report.",
            "plan": "Updates to protocol: …  Items shipped/picked up: …  Follow-up: …",
            "visit_type": "telehealth",
            "active": True,
        },
    ]
    for s in soap_seeds:
        if not await db.soap_templates.find_one({"title": s["title"]}):
            await db.soap_templates.insert_one({
                "id": new_id(),
                "created_by": None,
                "created_by_name": "Built-in",
                "created_at": now,
                "updated_at": now,
                **s,
            })
            logger.info("Seeded SOAP template: %s", s["title"])

    # Idempotent built-in detox protocol template
    if not await db.protocol_templates.find_one({"title": "Natural Medical Solutions Detox", "builtin": True}):
        await db.protocol_templates.insert_one({
            "id": new_id(),
            "builtin": True,
            "active": True,
            "title": "Natural Medical Solutions Detox",
            "description": "Configurable multi-week detoxification protocol with daily nutrition, recommended foods, and check-off treatment sessions.",
            "weeks": 4,
            "sessions_per_week": 2,
            "treatment_label": "Detox treatment",
            "daily_outline": (
                "**Breakfast** — 2 scoops Protein Plus Superfood Detox in 8 oz water/coconut water, "
                "blend with blueberries, strawberries, or raspberries, plus juice of half a lemon.\n\n"
                "**Lunch** — Same shake (with green apple or celery) plus a salad with chicken or wild-caught fish.\n\n"
                "**Dinner** — Salmon or bass with vegetables: asparagus, spinach, cauliflower, kale, bok choy, okra, zucchini.\n\n"
                "**Snacks** — Organic vegan protein bars, cucumber, celery, raspberries/strawberries, green apples. All ingredients organic."
            ),
            "foods_recommended": [
                "100% Berry Juices", "Apples", "Blueberries", "Raspberries", "Strawberries",
                "Arugula", "Bok Choy", "Cabbage", "Kale", "Onion", "Garlic", "Watercress",
                "Quinoa", "Buckwheat", "Millet", "Spelt", "Whole-grain rice",
                "Brazil nuts", "Pecans", "Walnuts", "Macadamia nuts",
                "Coconut milk", "Cashew milk", "Rice milk",
                "Extra virgin olive oil", "Coconut oil", "Flaxseed oil",
                "Organic green tea", "Organic herbal tea", "Purified water",
                "Chicken", "Cod", "Halibut", "Salmon", "Trout", "Tuna",
            ],
            "foods_avoid": [
                "Canned fruit packed in syrup", "High-sugar berry juices",
                "Soybean / soy-based foods", "Canned vegetables in sauces",
                "Gluten grains", "Refined flours", "Kamut",
                "Peanuts", "Chestnuts",
                "All dairy (milk, cheese, yogurt, ice-cream, whey)",
                "Butter", "Margarine", "Mayonnaise", "Hydrogenated oils",
                "Alcohol", "Coffee", "Black tea", "Sweetened beverages",
                "BBQ sauce", "Soy sauce", "Ketchup", "Cane sugar",
                "Processed meats", "Shellfish", "Fried foods", "Non-organic meats",
                "Artificial flavors / colors / preservatives (MSG)",
            ],
            "supplements": [],
            "lifestyle": (
                "• Use fresh herbs and spices for seasoning.\n"
                "• Avoid packaged and processed foods — organic only.\n"
                "• Drink at least 8 cups of water per day.\n"
                "• No dairy.\n"
                "• Eight hours of sleep nightly; gentle movement (walking, yoga) daily."
            ),
            "created_by": None,
            "created_by_name": "Built-in",
            "created_at": now,
            "updated_at": now,
        })
        logger.info("Seeded built-in detox protocol template.")


@app.on_event("shutdown")
async def shutdown_db_client():
    close_mongo()


app.include_router(api)

# --- Sprint 2 CORS ------------------------------------------------------ #
_allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "").strip()
_allowed_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
_hipaa_mode = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}
if _hipaa_mode and (not _allowed_origins or "*" in _allowed_origins):
    raise RuntimeError(
        "HIPAA_MODE=on: ALLOWED_ORIGINS must be an explicit comma-separated list — "
        "wildcard + credentials is refused by browsers and disallowed here."
    )
if _allowed_origins:
    # Credentialed CORS with explicit allowlist (production-safe)
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_origins=_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Dev/preview only: wildcard origins WITHOUT credentials. Refresh cookie
    # will only fire when the request explicitly sends withCredentials=true
    # AND the browser accepts our Set-Cookie for this preview origin.
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=False,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

