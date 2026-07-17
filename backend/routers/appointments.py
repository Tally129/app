"""
Phase 2: Appointments, Availability, Practitioners directory, Memberships,
Invoices, Treatment Plans, Reminder settings.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, Request

from audit import get_client_ip, log_audit
from deps import (
    _resolve_self_client, _strip_id, api, db, get_current_user, require_roles,
)
from notifiers import push_to_user
from models import (
    AppointmentIn, AppointmentOut, AppointmentUpdate,
    AvailabilityIn, AvailabilityOut,
    InvoiceIn, InvoiceOut, MarkPaidIn,
    MembershipIn, MembershipOut,
    PlanIn, PlanOut,
    ReminderSettings, new_id,
)

TIER_PRICES = {"essentials": 99.0, "core": 199.0, "vip": 299.0}


# =================== PHASE 2: APPOINTMENTS / AVAILABILITY / PLANS / MEMBERSHIPS / INVOICES / REMINDERS ===================

TIER_PRICES = {"essentials": 99.0, "core": 199.0, "vip": 299.0}


async def _hydrate_appt(a):
    a = _strip_id(a)
    if not a:
        return None
    if a.get("client_id"):
        c = await db.clients.find_one({"id": a["client_id"]})
        if c:
            a["client_name"] = c.get("full_name")
    if a.get("practitioner_id"):
        u = await db.users.find_one({"id": a["practitioner_id"]})
        if u:
            a["practitioner_name"] = u.get("full_name")
    return a


# ---------- Appointments ----------
@api.get("/appointments", response_model=List[AppointmentOut])
async def list_appointments(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    practitioner_id: Optional[str] = None,
    client_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    else:
        if client_id:
            q["client_id"] = client_id
        if practitioner_id:
            q["practitioner_id"] = practitioner_id
    if start:
        q.setdefault("start", {})["$gte"] = start
    if end:
        q.setdefault("start", {})["$lte"] = end
    items = await db.appointments.find(q).sort("start", 1).to_list(1000)
    return [await _hydrate_appt(i) for i in items]


@api.post("/appointments", response_model=AppointmentOut)
async def create_appointment(payload: AppointmentIn, request: Request, user=Depends(get_current_user)):
    # Clients can only book for themselves
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        if payload.client_id != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
        status_val = "requested"
    else:
        status_val = payload.status
    c = await db.clients.find_one({"id": payload.client_id})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    doc = payload.dict()
    doc["id"] = new_id()
    doc["status"] = status_val
    doc["created_at"] = datetime.now(timezone.utc)
    doc["created_by"] = user["id"]
    await db.appointments.insert_one(doc)

    # Auto-schedule reminder (stubbed)
    settings = await db.reminder_settings.find_one({"id": "singleton"}) or {}
    hours_before = settings.get("appointment_reminder_hours_before", 24)
    channels = settings.get("appointment_reminder_channels", ["email"])
    if settings.get("enabled", True):
        scheduled_at = doc["start"] - timedelta(hours=hours_before)
        for ch in channels:
            await db.reminders.insert_one({
                "id": new_id(),
                "appointment_id": doc["id"],
                "client_id": doc["client_id"],
                "channel": ch,
                "scheduled_at": scheduled_at,
                "sent_at": None,
                "status": "scheduled",
                "created_at": datetime.now(timezone.utc),
            })

    await log_audit(db, user["id"], user["email"], "appointment.create",
                    resource_type="appointment", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_appt(doc)


@api.put("/appointments/{appt_id}", response_model=AppointmentOut)
async def update_appointment(appt_id: str, payload: AppointmentUpdate, request: Request,
                             user=Depends(get_current_user)):
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or a["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
        # Clients may only cancel their own
        if payload.status and payload.status != "canceled":
            raise HTTPException(status_code=403, detail="Clients may only cancel")
        updates = {"status": "canceled"}
    else:
        updates = {k: v for k, v in payload.dict().items() if v is not None}
    await db.appointments.update_one({"id": appt_id}, {"$set": updates})
    # Visit-started push: when telehealth appointment moves to in_session, ping the client
    if updates.get("status") == "in_session" and a.get("visit_mode") == "telehealth":
        client_doc = await db.clients.find_one({"id": a.get("client_id")})
        if client_doc and client_doc.get("user_id"):
            await push_to_user(
                client_doc["user_id"],
                "Your provider is ready",
                "Tap to join your telehealth visit now.",
                url=f"/portal/visit/{appt_id}",
                tag=f"visit-{appt_id}",
            )
    await log_audit(db, user["id"], user["email"], "appointment.update",
                    resource_type="appointment", resource_id=appt_id,
                    metadata={"fields": list(updates.keys())},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    a = await db.appointments.find_one({"id": appt_id})
    return await _hydrate_appt(a)


# ---------- Availability ----------
@api.get("/availability", response_model=List[AvailabilityOut])
async def list_availability(practitioner_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {}
    if practitioner_id:
        q["practitioner_id"] = practitioner_id
    elif user["role"] == "practitioner":
        q["practitioner_id"] = user["id"]
    items = await db.availability.find(q).sort("weekday", 1).to_list(200)
    return [_strip_id(i) for i in items]


@api.post("/availability", response_model=AvailabilityOut)
async def create_availability(payload: AvailabilityIn, request: Request,
                              user=Depends(require_roles("practitioner", "admin"))):
    pid = payload.practitioner_id or user["id"]
    doc = payload.dict()
    doc["practitioner_id"] = pid
    doc["id"] = new_id()
    await db.availability.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "availability.create",
                    resource_type="availability", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.delete("/availability/{avail_id}")
async def delete_availability(avail_id: str, request: Request,
                              user=Depends(require_roles("practitioner", "admin"))):
    await db.availability.delete_one({"id": avail_id})
    await log_audit(db, user["id"], user["email"], "availability.delete",
                    resource_type="availability", resource_id=avail_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.get("/availability/slots")
async def availability_slots(
    practitioner_id: str,
    date: str,  # YYYY-MM-DD
    duration_min: int = 60,
    user=Depends(get_current_user),
):
    try:
        d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date")
    weekday = d.weekday()
    rules = await db.availability.find({"practitioner_id": practitioner_id, "weekday": weekday, "active": True}).to_list(50)
    if not rules:
        return {"date": date, "slots": []}
    day_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    taken = await db.appointments.find({
        "practitioner_id": practitioner_id,
        "start": {"$gte": day_start, "$lt": day_end},
        "status": {"$in": ["requested", "confirmed"]},
    }).to_list(200)
    slots = []
    for r in rules:
        sh, sm = map(int, r["start_time"].split(":"))
        eh, em = map(int, r["end_time"].split(":"))
        cur = day_start.replace(hour=sh, minute=sm)
        end = day_start.replace(hour=eh, minute=em)
        while cur + timedelta(minutes=duration_min) <= end:
            slot_end = cur + timedelta(minutes=duration_min)
            overlaps = any(
                not (t["end"] <= cur or t["start"] >= slot_end) for t in taken
            )
            if not overlaps:
                slots.append({"start": cur.isoformat(), "end": slot_end.isoformat()})
            cur = slot_end
    return {"date": date, "slots": slots}


# ---------- Practitioners directory (for patient booking) ----------
@api.get("/practitioners")
async def list_practitioners(user=Depends(get_current_user)):
    items = await db.users.find({"role": "practitioner", "is_active": True}).to_list(100)
    return [{"id": u["id"], "full_name": u.get("full_name"), "email": u["email"]} for u in items]


# ---------- Memberships ----------
async def _hydrate_mem(m):
    m = _strip_id(m)
    if not m:
        return None
    c = await db.clients.find_one({"id": m["client_id"]})
    if c:
        m["client_name"] = c.get("full_name")
    return m


@api.get("/memberships", response_model=List[MembershipOut])
async def list_memberships(user=Depends(require_roles("admin", "staff", "practitioner"))):
    items = await db.memberships.find().sort("created_at", -1).to_list(500)
    return [await _hydrate_mem(i) for i in items]


@api.get("/memberships/mine", response_model=Optional[MembershipOut])
async def my_membership(user=Depends(get_current_user)):
    self_client = await _resolve_self_client(user)
    if not self_client:
        return None
    m = await db.memberships.find_one({"client_id": self_client["id"], "status": {"$in": ["active", "pending", "paused"]}})
    return await _hydrate_mem(m) if m else None


@api.post("/memberships", response_model=MembershipOut)
async def create_membership(payload: MembershipIn, request: Request, user=Depends(get_current_user)):
    if payload.tier not in TIER_PRICES:
        raise HTTPException(status_code=400, detail="Invalid tier")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = self_client["id"]
    else:
        if not payload.client_id:
            raise HTTPException(status_code=400, detail="client_id required")
        client_id = payload.client_id

    # If stripe - create stubbed subscription id
    stripe_sub = None
    status_val = "pending"
    if payload.billing_method == "stripe":
        if not os.environ.get("STRIPE_SECRET_KEY"):
            # Stub flow
            stripe_sub = f"sub_stub_{new_id()[:8]}"
            await db.integration_log.insert_one({
                "id": new_id(), "service": "stripe", "action": "subscription.create",
                "payload": {"client_id": client_id, "tier": payload.tier},
                "_stubbed": True, "ts": datetime.now(timezone.utc),
            })
            status_val = "active"
        else:
            # Real wire-up point (left as stub entry for now)
            stripe_sub = f"sub_pending_{new_id()[:8]}"
            status_val = "pending"
    else:
        status_val = "active"  # chase_pos / manual — recorded, staff reconciles payment

    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(),
        "client_id": client_id,
        "tier": payload.tier,
        "price": TIER_PRICES[payload.tier],
        "status": status_val,
        "billing_method": payload.billing_method,
        "started_at": now if status_val == "active" else None,
        "next_bill_date": now + timedelta(days=30) if status_val == "active" else None,
        "stripe_subscription_id": stripe_sub,
        "created_at": now,
    }
    await db.memberships.insert_one(doc)

    # Auto-generate first invoice
    inv = {
        "id": new_id(),
        "client_id": client_id,
        "membership_id": doc["id"],
        "appointment_id": None,
        "description": f"Membership: {payload.tier.capitalize()} Wellness (first month)",
        "amount": TIER_PRICES[payload.tier],
        "status": "due",
        "paid_at": None,
        "payment_method": None,
        "external_ref": None,
        "created_at": now,
    }
    await db.invoices.insert_one(inv)

    await log_audit(db, user["id"], user["email"], "membership.create",
                    resource_type="membership", resource_id=doc["id"],
                    metadata={"tier": payload.tier, "method": payload.billing_method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_mem(doc)


@api.put("/memberships/{mem_id}/status", response_model=MembershipOut)
async def set_membership_status(mem_id: str, body: dict, request: Request,
                                user=Depends(require_roles("admin", "staff", "practitioner"))):
    status_val = (body or {}).get("status")
    if status_val not in ("active", "paused", "canceled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    await db.memberships.update_one({"id": mem_id}, {"$set": {"status": status_val}})
    await log_audit(db, user["id"], user["email"], "membership.status",
                    resource_type="membership", resource_id=mem_id, metadata={"status": status_val},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    m = await db.memberships.find_one({"id": mem_id})
    return await _hydrate_mem(m)


# ---------- Invoices ----------
async def _hydrate_invoice(i):
    i = _strip_id(i)
    if not i:
        return None
    c = await db.clients.find_one({"id": i["client_id"]})
    if c:
        i["client_name"] = c.get("full_name")
    return i


@api.get("/invoices", response_model=List[InvoiceOut])
async def list_invoices(client_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    items = await db.invoices.find(q).sort("created_at", -1).to_list(500)
    return [await _hydrate_invoice(i) for i in items]


@api.post("/invoices", response_model=InvoiceOut)
async def create_invoice(payload: InvoiceIn, request: Request,
                         user=Depends(require_roles("admin", "staff", "practitioner"))):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["status"] = "due"
    doc["paid_at"] = None
    doc["payment_method"] = None
    doc["external_ref"] = None
    doc["created_at"] = datetime.now(timezone.utc)
    await db.invoices.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "invoice.create",
                    resource_type="invoice", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id, "amount": payload.amount},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_invoice(doc)


@api.post("/invoices/{inv_id}/mark-paid", response_model=InvoiceOut)
async def mark_paid(inv_id: str, payload: MarkPaidIn, request: Request,
                    user=Depends(require_roles("admin", "staff", "practitioner"))):
    inv = await db.invoices.find_one({"id": inv_id})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    updates = {
        "status": "paid",
        "paid_at": datetime.now(timezone.utc),
        "payment_method": payload.method,
        "external_ref": payload.external_ref,
    }
    await db.invoices.update_one({"id": inv_id}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "invoice.mark_paid",
                    resource_type="invoice", resource_id=inv_id, metadata={"method": payload.method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    inv = await db.invoices.find_one({"id": inv_id})
    return await _hydrate_invoice(inv)


@api.post("/invoices/{inv_id}/stripe-intent")
async def stripe_intent(inv_id: str, user=Depends(get_current_user)):
    inv = await db.invoices.find_one({"id": inv_id})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    # Stubbed - would create PaymentIntent in real integration
    await db.integration_log.insert_one({
        "id": new_id(), "service": "stripe", "action": "payment_intent.create",
        "payload": {"invoice_id": inv_id, "amount_cents": int(inv["amount"] * 100)},
        "_stubbed": True, "ts": datetime.now(timezone.utc),
    })
    return {
        "client_secret": f"pi_stub_{new_id()[:12]}_secret_stub",
        "_stubbed": True,
        "note": "Set STRIPE_SECRET_KEY to enable real payments.",
    }


# ---------- Treatment Plans ----------
async def _hydrate_plan(p, user=None):
    p = _strip_id(p)
    if not p:
        return None
    if p.get("practitioner_id"):
        u = await db.users.find_one({"id": p["practitioner_id"]})
        if u:
            p["practitioner_name"] = u.get("full_name")
    # Clients only see patient_visible items
    if user and user.get("role") == "client":
        p["items"] = [i for i in (p.get("items") or []) if i.get("patient_visible")]
    return p


@api.get("/treatment-plans", response_model=List[PlanOut])
async def list_plans(client_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    items = await db.treatment_plans.find(q).sort("created_at", -1).to_list(200)
    return [await _hydrate_plan(i, user) for i in items]


@api.post("/treatment-plans", response_model=PlanOut)
async def create_plan(payload: PlanIn, request: Request,
                      user=Depends(require_roles("practitioner", "admin"))):
    c = await db.clients.find_one({"id": payload.client_id})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    doc = payload.dict()
    doc["id"] = new_id()
    doc["practitioner_id"] = user["id"]
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = doc["created_at"]
    await db.treatment_plans.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "plan.create",
                    resource_type="plan", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_plan(doc, user)


@api.put("/treatment-plans/{plan_id}", response_model=PlanOut)
async def update_plan(plan_id: str, payload: PlanIn, request: Request,
                      user=Depends(require_roles("practitioner", "admin"))):
    p = await db.treatment_plans.find_one({"id": plan_id})
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    updates = payload.dict()
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.treatment_plans.update_one({"id": plan_id}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "plan.update",
                    resource_type="plan", resource_id=plan_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    p = await db.treatment_plans.find_one({"id": plan_id})
    return await _hydrate_plan(p, user)


# ---------- Reminder settings ----------
@api.get("/reminders/settings", response_model=ReminderSettings)
async def get_reminder_settings(user=Depends(require_roles("admin"))):
    s = await db.reminder_settings.find_one({"id": "singleton"})
    if not s:
        return ReminderSettings()
    return ReminderSettings(**{k: v for k, v in s.items() if k in ReminderSettings.model_fields})


@api.put("/reminders/settings", response_model=ReminderSettings)
async def set_reminder_settings(payload: ReminderSettings, request: Request, user=Depends(require_roles("admin"))):
    doc = {"id": "singleton", **payload.dict()}
    await db.reminder_settings.update_one({"id": "singleton"}, {"$set": doc}, upsert=True)
    await log_audit(db, user["id"], user["email"], "reminders.settings_update",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return payload


@api.post("/reminders/run")
async def run_reminders(user=Depends(require_roles("admin"))):
    """Manually tick the reminder scheduler: send due reminders (stubbed)."""
    now = datetime.now(timezone.utc)
    due = await db.reminders.find({"status": "scheduled", "scheduled_at": {"$lte": now}}).to_list(200)
    sent = 0
    for r in due:
        # Stubbed send via SendGrid/Twilio
        await db.integration_log.insert_one({
            "id": new_id(),
            "service": "sendgrid" if r["channel"] == "email" else "twilio",
            "action": f"reminder.{r['channel']}",
            "payload": {"appointment_id": r["appointment_id"], "client_id": r["client_id"]},
            "_stubbed": True, "ts": now,
        })
        await db.reminders.update_one({"id": r["id"]}, {"$set": {"status": "sent", "sent_at": now}})
        sent += 1
    return {"processed": sent}

