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
from routers import ops as _ops_routes  # noqa: F401
from routers import telehealth as _telehealth_routes  # noqa: F401
from routers import forms_protocols as _forms_protocols_routes  # noqa: F401
from routers import compliance as _compliance_routes  # noqa: F401


app = FastAPI(title="NatMedSol EMR API")



# =================== CLIENTS ===================
@api.get("/clients", response_model=List[ClientOut])
async def list_clients(user=Depends(require_roles("admin", "practitioner", "staff"))):
    items = await db.clients.find().sort("created_at", -1).to_list(500)
    return [_strip_id(i) for i in items]


@api.get("/clients/me", response_model=ClientOut)
async def my_client_record(user=Depends(get_current_user)):
    c = await _resolve_self_client(user)
    if not c:
        raise HTTPException(status_code=404, detail="No client record")
    return _strip_id(c)


@api.get("/clients/{client_id}", response_model=ClientOut)
async def get_client(client_id: str, request: Request, user=Depends(get_current_user)):
    c = await db.clients.find_one({"id": client_id})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    if user["role"] == "client" and c.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await log_audit(db, user["id"], user["email"], "client.read",
                    resource_type="client", resource_id=client_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(c)


@api.post("/clients", response_model=ClientOut)
async def create_client(payload: ClientIn, request: Request,
                        user=Depends(require_roles("admin", "staff", "practitioner"))):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["intake_completed"] = False
    doc["created_at"] = datetime.now(timezone.utc)
    # Auto-generate MRN if not provided: NMS- + 6-char hex
    if not doc.get("mrn"):
        doc["mrn"] = f"NMS-{doc['id'][:6].upper()}"
    await db.clients.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "client.create",
                    resource_type="client", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/clients/{client_id}", response_model=ClientOut)
async def update_client(client_id: str, payload: ClientIn, request: Request,
                        user=Depends(require_roles("admin", "staff", "practitioner"))):
    c = await db.clients.find_one({"id": client_id})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    await db.clients.update_one({"id": client_id}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "client.update",
                    resource_type="client", resource_id=client_id,
                    metadata={"fields": list(updates.keys())},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    c = await db.clients.find_one({"id": client_id})
    return _strip_id(c)


# =================== INTAKE ===================
@api.post("/intake", response_model=IntakeOut)
async def save_intake(payload: IntakeIn, request: Request, user=Depends(get_current_user)):
    if user["role"] == "client":
        target_client = await _resolve_self_client(user)
        if not target_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = target_client["id"]
    else:
        if not payload.client_id:
            raise HTTPException(status_code=400, detail="client_id required")
        target_client = await db.clients.find_one({"id": payload.client_id})
        if not target_client:
            raise HTTPException(status_code=404, detail="Client not found")
        client_id = payload.client_id

    existing = await db.intake_forms.find_one({"client_id": client_id})
    data = payload.dict()
    data["client_id"] = client_id
    now = datetime.now(timezone.utc)
    data["signed_at"] = now if data.get("consent", {}).get("signed") else None

    if existing:
        data["id"] = existing["id"]
        data["created_at"] = existing.get("created_at", now)
        if payload.completed:
            data["completed_at"] = now
        await db.intake_forms.update_one({"id": existing["id"]}, {"$set": data})
    else:
        data["id"] = new_id()
        data["created_at"] = now
        if payload.completed:
            data["completed_at"] = now
        await db.intake_forms.insert_one(data)

    if payload.completed:
        await db.clients.update_one({"id": client_id}, {"$set": {"intake_completed": True}})

    await log_audit(db, user["id"], user["email"], "intake.save",
                    resource_type="intake", resource_id=data["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(data)


@api.get("/intake/{client_id}")
async def get_intake(client_id: str, request: Request, user=Depends(get_current_user)):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or self_client["id"] != client_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    intake = await db.intake_forms.find_one({"client_id": client_id})
    if not intake:
        return None
    await log_audit(db, user["id"], user["email"], "intake.read",
                    resource_type="intake", resource_id=intake["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(intake)


# =================== SOAP NOTES ===================
@api.get("/notes", response_model=List[NoteOut])
async def list_notes(request: Request, client_id: str = Query(...),
                     user=Depends(get_current_user)):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or self_client["id"] != client_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    items = await db.visit_notes.find({"client_id": client_id}).sort("created_at", -1).to_list(500)
    await log_audit(db, user["id"], user["email"], "note.list",
                    resource_type="client", resource_id=client_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return [_strip_id(i) for i in items]


@api.get("/notes/all", response_model=List[NoteOut])
async def list_all_notes(request: Request,
                         practitioner_id: Optional[str] = None,
                         search: Optional[str] = None,
                         limit: int = 200,
                         user=Depends(require_roles("admin", "practitioner", "staff"))):
    """Clinic-wide notes index for admin/practitioner/staff drill-down screens.
    Optional filters: practitioner_id (author), search (matches client_name)."""
    q: Dict[str, Any] = {}
    if practitioner_id:
        q["practitioner_id"] = practitioner_id
    rows = await db.visit_notes.find(q).sort("created_at", -1).to_list(limit)
    # Hydrate with client_name
    client_ids = list({r.get("client_id") for r in rows if r.get("client_id")})
    clients = {c["id"]: c async for c in db.clients.find({"id": {"$in": client_ids}})}
    out = []
    for r in rows:
        c = clients.get(r.get("client_id")) or {}
        cname = c.get("full_name") or c.get("email") or ""
        if search and search.lower() not in cname.lower():
            continue
        d = _strip_id(r)
        d["client_name"] = cname
        out.append(d)
    await log_audit(db, user["id"], user["email"], "note.list_all",
                    resource_type="notes",
                    metadata={"count": len(out)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return out


@api.post("/notes", response_model=NoteOut)
async def create_note(payload: NoteIn, request: Request,
                      user=Depends(require_roles("practitioner", "admin"))):
    c = await db.clients.find_one({"id": payload.client_id})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    doc = payload.dict()
    doc["id"] = new_id()
    doc["practitioner_id"] = user["id"]
    doc["practitioner_name"] = user.get("full_name", "")
    doc["amendments"] = []
    doc["created_at"] = datetime.now(timezone.utc)
    await db.visit_notes.insert_one(doc)

    # ---- Phase 14: auto-attach referenced supplement directions to the patient chart ----
    matched = await _fan_out_supplements_for_note(doc, user)
    if matched:
        doc["auto_attached_supplements"] = matched
    await log_audit(db, user["id"], user["email"], "note.create",
                    resource_type="note", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id, "auto_attached": [m["sheet_id"] for m in matched]},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


async def _fan_out_supplements_for_note(note: dict, user: dict) -> list:
    """Scan a SOAP note's free-text fields for references to active supplement
    sheets (case-insensitive substring on title) and create assignment rows so
    the patient's portal "My Plan" page surfaces those PDFs automatically."""
    haystack = " ".join([
        note.get("subjective") or "",
        note.get("objective") or "",
        note.get("assessment") or "",
        note.get("plan") or "",
    ]).lower()
    if not haystack.strip():
        return []
    sheets = await db.supplement_sheets.find({"active": True}).to_list(200)
    matched = []
    now = datetime.now(timezone.utc)
    for s in sheets:
        title = (s.get("title") or "").strip()
        if len(title) < 4:
            continue  # avoid spurious matches on tiny titles
        if title.lower() in haystack:
            # idempotent — only create when not already linked
            existing = await db.client_supplement_assignments.find_one({
                "client_id": note["client_id"], "sheet_id": s["id"], "active": True,
            })
            if existing:
                # bump last_referenced + add note ref
                await db.client_supplement_assignments.update_one(
                    {"id": existing["id"]},
                    {"$set": {"last_referenced_at": now}, "$addToSet": {"note_ids": note["id"]}},
                )
                matched.append({"sheet_id": s["id"], "sheet_title": title, "assignment_id": existing["id"], "newly_assigned": False})
            else:
                a = {
                    "id": new_id(),
                    "client_id": note["client_id"],
                    "sheet_id": s["id"],
                    "sheet_title": title,
                    "sheet_summary": s.get("summary") or "",
                    "items_snapshot": s.get("items") or [],
                    "active": True,
                    "assigned_by_id": user["id"],
                    "assigned_by_name": user.get("full_name") or "",
                    "assigned_at": now,
                    "last_referenced_at": now,
                    "note_ids": [note["id"]],
                    "source": "auto_soap",
                }
                await db.client_supplement_assignments.insert_one(a)
                matched.append({"sheet_id": s["id"], "sheet_title": title, "assignment_id": a["id"], "newly_assigned": True})
                # Mirror to audit log so admins have a single trail regardless of source
                try:
                    await log_audit(db, user["id"], user["email"], "supplement_assignment.create",
                                    resource_type="client", resource_id=note["client_id"],
                                    metadata={"sheet_id": s["id"], "source": "auto_soap", "note_id": note["id"]})
                except Exception:
                    pass
                # Push notification to the client portal user
                try:
                    if c_user_id := (await db.clients.find_one({"id": note["client_id"]})).get("user_id"):
                        await push_to_user(
                            c_user_id,
                            "New supplement directions",
                            f"Dr. {user.get('full_name') or ''} attached \"{title}\" to your plan.",
                            url="/portal/patient/plan",
                            tag=f"supp-{a['id']}",
                        )
                except Exception:
                    pass
    return matched


# ---- Client supplement assignments CRUD ----
@api.get("/clients/{client_id}/supplement-assignments")
async def list_client_supplement_assignments(client_id: str, user=Depends(get_current_user)):
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or sc["id"] != client_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    rows = await db.client_supplement_assignments.find({"client_id": client_id, "active": True}).sort("assigned_at", -1).to_list(200)
    return [_strip_id(r) for r in rows]


@api.post("/clients/{client_id}/supplement-assignments")
async def create_client_supplement_assignment(client_id: str, payload: dict, request: Request,
                                              user=Depends(require_roles("admin", "practitioner"))):
    sheet_id = payload.get("sheet_id")
    if not sheet_id:
        raise HTTPException(status_code=400, detail="sheet_id required")
    sheet = await db.supplement_sheets.find_one({"id": sheet_id})
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet not found")
    client = await db.clients.find_one({"id": client_id})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    existing = await db.client_supplement_assignments.find_one({"client_id": client_id, "sheet_id": sheet_id, "active": True})
    if existing:
        return _strip_id(existing)
    now = datetime.now(timezone.utc)
    a = {
        "id": new_id(),
        "client_id": client_id,
        "sheet_id": sheet_id,
        "sheet_title": sheet.get("title"),
        "sheet_summary": sheet.get("summary") or "",
        "items_snapshot": sheet.get("items") or [],
        "active": True,
        "assigned_by_id": user["id"],
        "assigned_by_name": user.get("full_name"),
        "assigned_at": now,
        "last_referenced_at": now,
        "note_ids": [],
        "source": "manual",
    }
    await db.client_supplement_assignments.insert_one(a)
    await log_audit(db, user["id"], user["email"], "supplement_assignment.create",
                    resource_type="client", resource_id=client_id,
                    metadata={"sheet_id": sheet_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(a)


@api.delete("/clients/{client_id}/supplement-assignments/{assignment_id}")
async def remove_client_supplement_assignment(client_id: str, assignment_id: str, request: Request,
                                              user=Depends(require_roles("admin", "practitioner"))):
    a = await db.client_supplement_assignments.find_one({"id": assignment_id})
    if not a or a.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.client_supplement_assignments.update_one({"id": assignment_id}, {"$set": {"active": False, "removed_at": datetime.now(timezone.utc), "removed_by_id": user["id"]}})
    await log_audit(db, user["id"], user["email"], "supplement_assignment.remove",
                    resource_type="client", resource_id=client_id,
                    metadata={"assignment_id": assignment_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/notes/{note_id}/amend", response_model=NoteOut)
async def amend_note(note_id: str, payload: AmendIn, request: Request,
                     user=Depends(require_roles("practitioner", "admin"))):
    note = await db.visit_notes.find_one({"id": note_id})
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    amendment = {
        "author_id": user["id"],
        "author_name": user.get("full_name", ""),
        "content": payload.content,
        "ts": datetime.now(timezone.utc),
    }
    await db.visit_notes.update_one({"id": note_id}, {"$push": {"amendments": amendment}})
    await log_audit(db, user["id"], user["email"], "note.amend",
                    resource_type="note", resource_id=note_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    note = await db.visit_notes.find_one({"id": note_id})
    return _strip_id(note)


# =================== FILES ===================
ALLOWED_CATEGORIES = {"lab", "intake", "image", "doc", "other"}


@api.post("/files/upload", response_model=FileMetaOut)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    client_id: Optional[str] = Form(None),
    category: str = Form("other"),
    user=Depends(get_current_user),
):
    if category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Category must be one of {ALLOWED_CATEGORIES}")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = self_client["id"]
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (20MB max)")
    gridfs_id = await fs_bucket.upload_from_stream(file.filename, io.BytesIO(content),
                                                   metadata={"mime": file.content_type})
    meta = {
        "id": new_id(),
        "gridfs_id": str(gridfs_id),
        "filename": file.filename,
        "mime": file.content_type or "application/octet-stream",
        "size": len(content),
        "category": category,
        "client_id": client_id,
        "uploaded_by": user["id"],
        "uploaded_by_name": user.get("full_name", ""),
        "created_at": datetime.now(timezone.utc),
    }
    await db.files.insert_one(meta)
    await log_audit(db, user["id"], user["email"], "file.upload",
                    resource_type="file", resource_id=meta["id"],
                    metadata={"client_id": client_id, "category": category, "size": len(content)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(meta)


@api.get("/files", response_model=List[FileMetaOut])
async def list_files(client_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    items = await db.files.find(q).sort("created_at", -1).to_list(500)
    return [_strip_id(i) for i in items]


@api.get("/files/{file_id}/download")
async def download_file(file_id: str, request: Request, user=Depends(get_current_user)):
    meta = await db.files.find_one({"id": file_id})
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or meta.get("client_id") != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    try:
        stream = await fs_bucket.open_download_stream(ObjectId(meta["gridfs_id"]))
    except Exception:
        raise HTTPException(status_code=404, detail="File not found in storage")
    data = await stream.read()
    await log_audit(db, user["id"], user["email"], "file.download",
                    resource_type="file", resource_id=file_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    fname = meta["filename"].replace('"', "")
    return StreamingResponse(
        io.BytesIO(data),
        media_type=meta.get("mime", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# =================== DASHBOARD ===================
@api.get("/dashboard/stats")
async def dashboard_stats(user=Depends(get_current_user)):
    role = user["role"]
    if role in ("admin", "staff"):
        return {
            "role": role,
            "clients": await db.clients.count_documents({}),
            "notes": await db.visit_notes.count_documents({}),
            "files": await db.files.count_documents({}),
            "appointments_requested": await db.appointment_requests.count_documents({}),
            "users": await db.users.count_documents({}),
            "audit_events": await db.audit_logs.count_documents({}),
        }
    if role == "practitioner":
        return {
            "role": role,
            "my_patients": await db.clients.count_documents({"assigned_practitioner_id": user["id"]}),
            "total_clients": await db.clients.count_documents({}),
            "my_notes": await db.visit_notes.count_documents({"practitioner_id": user["id"]}),
        }
    self_client = await _resolve_self_client(user)
    if not self_client:
        return {"role": role}
    return {
        "role": role,
        "client_id": self_client["id"],
        "intake_completed": self_client.get("intake_completed", False),
        "notes": await db.visit_notes.count_documents({"client_id": self_client["id"]}),
        "files": await db.files.count_documents({"client_id": self_client["id"]}),
    }


# =================== ADMIN ===================
@api.get("/admin/audit", response_model=List[AuditLogOut])
async def admin_audit(limit: int = 100, user_id: Optional[str] = None, action: Optional[str] = None,
                      user=Depends(require_roles("admin"))):
    q = {}
    if user_id:
        q["user_id"] = user_id
    if action:
        q["action"] = action
    items = await db.audit_logs.find(q).sort("ts", -1).to_list(min(limit, 500))
    return [_strip_id(i) for i in items]


@api.get("/admin/users", response_model=List[UserOut])
async def admin_users(user=Depends(require_roles("admin"))):
    items = await db.users.find().sort("created_at", -1).to_list(500)
    return [to_user_out(_strip_id(i)) for i in items]


@api.post("/admin/users", response_model=UserOut)
async def admin_create_user(payload: UserCreate, request: Request, user=Depends(require_roles("admin"))):
    if payload.role not in ("admin", "practitioner", "staff", "client"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if await db.users.find_one({"email": payload.email.lower()}):
        raise HTTPException(status_code=409, detail="Email already registered")
    doc = {
        "id": new_id(),
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "full_name": payload.full_name,
        "phone": payload.phone,
        "role": payload.role,
        "mfa_enabled": False,
        "mfa_secret": None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }
    await db.users.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "admin.create_user",
                    resource_type="user", resource_id=doc["id"],
                    metadata={"role": payload.role},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return to_user_out(doc)


@api.put("/admin/users/{user_id}/role", response_model=UserOut)
async def admin_update_role(user_id: str, body: dict, request: Request, user=Depends(require_roles("admin"))):
    role = (body or {}).get("role")
    if role not in ("admin", "practitioner", "staff", "client"):
        raise HTTPException(status_code=400, detail="Invalid role")
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one({"id": user_id}, {"$set": {"role": role}})
    await log_audit(db, user["id"], user["email"], "admin.update_role",
                    resource_type="user", resource_id=user_id, metadata={"role": role},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    target = await db.users.find_one({"id": user_id})
    return to_user_out(target)



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
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}



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
def _send_push_to_user(sub_doc, payload):
    try:
        from pywebpush import webpush, WebPushException
        webpush(
            subscription_info={
                "endpoint": sub_doc["endpoint"],
                "keys": sub_doc.get("keys", {}),
            },
            data=json.dumps(payload),
            vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", ""),
            vapid_claims={"sub": os.environ.get("VAPID_CONTACT", "mailto:admin@natmedsol.local")},
            ttl=60 * 60 * 24,
        )
        return True
    except Exception as e:
        logger.info("push send failed for %s: %s", sub_doc.get("endpoint", "?")[:40], e)
        return False


async def push_to_user(user_id, title, body, url="/portal", tag=None):
    """Best-effort push to all active subscriptions for a user. Drops 404/410 endpoints."""
    if not os.environ.get("VAPID_PRIVATE_KEY"):
        return 0
    subs = await db.push_subscriptions.find({"user_id": user_id}).to_list(20)
    sent = 0
    payload = {"title": title, "body": body, "url": url, "tag": tag or title}
    dead = []
    for s in subs:
        ok = _send_push_to_user(s, payload)
        if ok:
            sent += 1
        else:
            dead.append(s["endpoint"])
    # cleanup dead endpoints
    if dead:
        await db.push_subscriptions.delete_many({"endpoint": {"$in": dead}})
    return sent


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
    resp = await call_next(request)
    # HSTS — force HTTPS for 1 year, include subdomains
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(self), camera=(self)"
    return resp

@app.on_event("startup")
async def seed_demo():
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
    except Exception as e:
        logger.warning("Index creation warning: %s", e)

    # Background tasks for push triggers
    _asyncio.create_task(_appointment_reminder_loop())
    _asyncio.create_task(_expiring_inventory_loop())

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
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
