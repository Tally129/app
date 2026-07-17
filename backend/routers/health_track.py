"""
Phase 3: Symptom logs + Lab values + Secure messaging.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, Request

from audit import get_client_ip, log_audit
from deps import (
    _resolve_self_client, _strip_id, api, db, get_current_user, require_roles,
)
from models import (
    LabValueIn, LabValueOut, MessageIn, MessageOut,
    SymptomLogIn, SymptomLogOut, ThreadIn, ThreadOut, new_id,
)


# =================== PHASE 3: SYMPTOMS / LABS / MESSAGING + TELEHEALTH ===================


# ---------- Symptom logs ----------
TRACKED_SYMPTOMS = [
    "Fatigue", "Pain", "Sleep", "Mood", "Digestion", "Anxiety",
    "Headache", "Brain fog", "Energy", "Stress",
]


@api.get("/symptoms/presets")
async def symptom_presets(user=Depends(get_current_user)):
    return {"symptoms": TRACKED_SYMPTOMS}


@api.post("/symptom-logs", response_model=SymptomLogOut)
async def log_symptom(payload: SymptomLogIn, request: Request, user=Depends(get_current_user)):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = self_client["id"]
    else:
        if not payload.client_id:
            raise HTTPException(status_code=400, detail="client_id required")
        client_id = payload.client_id

    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(),
        "client_id": client_id,
        "symptom": payload.symptom,
        "severity": payload.severity,
        "note": payload.note,
        "logged_at": payload.logged_at or now,
        "created_at": now,
    }
    await db.symptom_logs.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "symptom.log",
                    resource_type="symptom", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.get("/symptom-logs", response_model=List[SymptomLogOut])
async def list_symptoms(client_id: Optional[str] = None, symptom: Optional[str] = None,
                        user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    if symptom:
        q["symptom"] = symptom
    items = await db.symptom_logs.find(q).sort("logged_at", 1).to_list(1000)
    return [_strip_id(i) for i in items]


# ---------- Lab values ----------
LAB_PRESETS = [
    {"test_name": "TSH", "unit": "mIU/L", "reference_low": 0.4, "reference_high": 4.0},
    {"test_name": "Free T3", "unit": "pg/mL", "reference_low": 2.3, "reference_high": 4.2},
    {"test_name": "Free T4", "unit": "ng/dL", "reference_low": 0.8, "reference_high": 1.8},
    {"test_name": "Vitamin D", "unit": "ng/mL", "reference_low": 30, "reference_high": 100},
    {"test_name": "Vitamin B12", "unit": "pg/mL", "reference_low": 200, "reference_high": 900},
    {"test_name": "A1C", "unit": "%", "reference_low": 4.0, "reference_high": 5.6},
    {"test_name": "Glucose (fasting)", "unit": "mg/dL", "reference_low": 70, "reference_high": 99},
    {"test_name": "Cortisol (AM)", "unit": "mcg/dL", "reference_low": 6, "reference_high": 23},
    {"test_name": "DHEA-S", "unit": "mcg/dL", "reference_low": 35, "reference_high": 430},
]


@api.get("/labs/presets")
async def lab_presets(user=Depends(get_current_user)):
    return {"presets": LAB_PRESETS}


@api.post("/lab-values", response_model=LabValueOut)
async def create_lab(payload: LabValueIn, request: Request, user=Depends(require_roles("practitioner", "admin", "staff"))):
    c = await db.clients.find_one({"id": payload.client_id})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    doc = payload.dict()
    doc["id"] = new_id()
    doc["recorded_by"] = user["id"]
    doc["recorded_by_name"] = user.get("full_name", "")
    doc["created_at"] = datetime.now(timezone.utc)
    await db.lab_values.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "lab.create",
                    resource_type="lab", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id, "test": payload.test_name},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.get("/lab-values", response_model=List[LabValueOut])
async def list_labs(client_id: Optional[str] = None, test_name: Optional[str] = None,
                    user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    if test_name:
        q["test_name"] = test_name
    items = await db.lab_values.find(q).sort("measured_at", 1).to_list(1000)
    return [_strip_id(i) for i in items]


@api.delete("/lab-values/{lab_id}")
async def delete_lab(lab_id: str, request: Request, user=Depends(require_roles("practitioner", "admin"))):
    await db.lab_values.delete_one({"id": lab_id})
    await log_audit(db, user["id"], user["email"], "lab.delete",
                    resource_type="lab", resource_id=lab_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


# ---------- Secure Messaging ----------
MESSAGE_TEMPLATES = [
    {"id": "follow_up", "label": "Follow-up reminder", "body": "This is a friendly reminder about your follow-up visit. Please log in to the portal to schedule."},
    {"id": "intake_pending", "label": "Intake pending", "body": "We noticed your intake is not yet complete. Please finish it in the portal before your visit."},
    {"id": "labs_ready", "label": "Results available", "body": "Your latest results are now available in the portal. Please log in to review and message us with any questions."},
    {"id": "schedule_visit", "label": "Schedule your next visit", "body": "It's time to book your next wellness visit. Please use the portal to pick a time that works for you."},
    {"id": "thanks", "label": "Thank you", "body": "Thank you for visiting Natural Medical Solutions. We're here if any questions come up."},
]


@api.get("/messages/templates")
async def message_templates(user=Depends(get_current_user)):
    return {"templates": MESSAGE_TEMPLATES}


async def _thread_other_role(role: str) -> str:
    return "practitioner" if role == "client" else "client"


async def _hydrate_thread(t, user):
    t = _strip_id(t)
    if not t:
        return None
    c = await db.clients.find_one({"id": t["client_id"]})
    if c:
        t["client_name"] = c.get("full_name")
    p = await db.users.find_one({"id": t["practitioner_id"]})
    if p:
        t["practitioner_name"] = p.get("full_name")
    # Count unread for current user
    unread = await db.messages.count_documents({"thread_id": t["id"], "read_by": {"$ne": user["id"]}, "sender_id": {"$ne": user["id"]}})
    t["unread_for_me"] = unread
    return t


@api.get("/messages/threads", response_model=List[ThreadOut])
async def list_threads(user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif user["role"] in ("practitioner",):
        q["practitioner_id"] = user["id"]
    items = await db.message_threads.find(q).sort("last_message_at", -1).to_list(200)
    return [await _hydrate_thread(t, user) for t in items]


@api.post("/messages/threads", response_model=ThreadOut)
async def create_thread(payload: ThreadIn, request: Request, user=Depends(get_current_user)):
    # Resolve client + practitioner
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = self_client["id"]
        practitioner_id = payload.participant_id
        p = await db.users.find_one({"id": practitioner_id})
        if not p or p.get("role") not in ("practitioner", "admin", "staff"):
            raise HTTPException(status_code=400, detail="Invalid practitioner")
    else:
        c = await db.clients.find_one({"id": payload.participant_id})
        if not c:
            raise HTTPException(status_code=404, detail="Client not found")
        client_id = c["id"]
        practitioner_id = user["id"]

    doc = {
        "id": new_id(),
        "client_id": client_id,
        "practitioner_id": practitioner_id,
        "subject": payload.subject,
        "last_message_at": None,
        "last_message_preview": None,
        "created_at": datetime.now(timezone.utc),
    }
    await db.message_threads.insert_one(doc)

    if payload.first_message:
        msg = {
            "id": new_id(),
            "thread_id": doc["id"],
            "sender_id": user["id"],
            "sender_role": user["role"],
            "sender_name": user.get("full_name", ""),
            "body": payload.first_message,
            "attachment_file_ids": [],
            "read_by": [user["id"]],
            "created_at": datetime.now(timezone.utc),
        }
        await db.messages.insert_one(msg)
        await db.message_threads.update_one({"id": doc["id"]}, {"$set": {
            "last_message_at": msg["created_at"],
            "last_message_preview": payload.first_message[:140],
        }})

    await log_audit(db, user["id"], user["email"], "message.thread_create",
                    resource_type="thread", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    t = await db.message_threads.find_one({"id": doc["id"]})
    return await _hydrate_thread(t, user)


@api.get("/messages/threads/{thread_id}", response_model=List[MessageOut])
async def list_messages(thread_id: str, request: Request, user=Depends(get_current_user)):
    t = await db.message_threads.find_one({"id": thread_id})
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or t["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif user["role"] == "practitioner" and t["practitioner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    items = await db.messages.find({"thread_id": thread_id}).sort("created_at", 1).to_list(500)
    # Mark read for this user
    await db.messages.update_many({"thread_id": thread_id, "read_by": {"$ne": user["id"]}},
                                  {"$push": {"read_by": user["id"]}})
    await log_audit(db, user["id"], user["email"], "message.thread_read",
                    resource_type="thread", resource_id=thread_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return [_strip_id(i) for i in items]


@api.post("/messages/threads/{thread_id}/messages", response_model=MessageOut)
async def post_message(thread_id: str, payload: MessageIn, request: Request, user=Depends(get_current_user)):
    t = await db.message_threads.find_one({"id": thread_id})
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or t["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif user["role"] == "practitioner" and t["practitioner_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    now = datetime.now(timezone.utc)
    msg = {
        "id": new_id(),
        "thread_id": thread_id,
        "sender_id": user["id"],
        "sender_role": user["role"],
        "sender_name": user.get("full_name", ""),
        "body": payload.body,
        "attachment_file_ids": payload.attachment_file_ids or [],
        "read_by": [user["id"]],
        "created_at": now,
    }
    await db.messages.insert_one(msg)
    await db.message_threads.update_one({"id": thread_id}, {"$set": {
        "last_message_at": now,
        "last_message_preview": payload.body[:140],
    }})
    # Push: notify other thread participants
    thread = await db.message_threads.find_one({"id": thread_id})
    sender_name = user.get("full_name") or user.get("email", "")
    for pid in (thread or {}).get("participant_ids", []):
        if pid != user["id"]:
            await push_to_user(
                pid,
                f"New message from {sender_name}",
                payload.body[:120],
                url="/portal/patient/messages" if (await db.users.find_one({"id": pid}) or {}).get("role") == "client" else "/portal/provider/messages",
                tag=f"msg-{thread_id}",
            )
    await log_audit(db, user["id"], user["email"], "message.send",
                    resource_type="thread", resource_id=thread_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(msg)


@api.get("/messages/unread-count")
async def messages_unread_count(user=Depends(get_current_user)):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return {"count": 0}
        threads = await db.message_threads.find({"client_id": self_client["id"]}).to_list(500)
    elif user["role"] == "practitioner":
        threads = await db.message_threads.find({"practitioner_id": user["id"]}).to_list(500)
    else:
        return {"count": 0}
    count = 0
    for t in threads:
        c = await db.messages.count_documents({"thread_id": t["id"], "read_by": {"$ne": user["id"]}, "sender_id": {"$ne": user["id"]}})
        count += c
    return {"count": count}




