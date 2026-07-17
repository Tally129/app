from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from bson import ObjectId
import os
import io
import json
import logging
from pathlib import Path
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
    hash_password, verify_password,
    make_access_token, make_refresh_token, decode_token,
    generate_mfa_secret, mfa_provisioning_uri, verify_mfa,
)
from audit import log_audit, get_client_ip


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
_client = AsyncIOMotorClient(mongo_url)
db = _client[os.environ["DB_NAME"]]
fs_bucket = AsyncIOMotorGridFSBucket(db, bucket_name="emr_files")

app = FastAPI(title="NatMedSol EMR API")
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logger = logging.getLogger("nms.emr")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _strip_id(doc):
    if doc is None:
        return None
    d = dict(doc)
    d.pop("_id", None)
    return d


async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
):
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing auth token")
    payload = decode_token(creds.credentials)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not an access token")
    user = await db.users.find_one({"id": payload["sub"]})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    return user


def require_roles(*roles):
    async def dep(user=Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dep


def to_user_out(user) -> dict:
    if user is None:
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user.get("full_name", ""),
        "phone": user.get("phone"),
        "role": user.get("role", "client"),
        "mfa_enabled": user.get("mfa_enabled", False),
        "is_active": user.get("is_active", True),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


async def _resolve_self_client(user) -> Optional[dict]:
    return await db.clients.find_one({"user_id": user["id"]})


# =================== AUTH ===================
@api.post("/auth/register", response_model=TokenOut)
async def register(payload: UserCreate, request: Request):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    role = "client"
    user_doc = {
        "id": new_id(),
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "full_name": payload.full_name,
        "phone": payload.phone,
        "role": role,
        "mfa_enabled": False,
        "mfa_secret": None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }
    await db.users.insert_one(user_doc)

    client_doc = {
        "id": new_id(),
        "user_id": user_doc["id"],
        "full_name": payload.full_name,
        "email": payload.email.lower(),
        "phone": payload.phone,
        "intake_completed": False,
        "created_at": datetime.now(timezone.utc),
    }
    await db.clients.insert_one(client_doc)

    await log_audit(db, user_doc["id"], user_doc["email"], "auth.register",
                    resource_type="user", resource_id=user_doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    access = make_access_token(user_doc["id"], role)
    refresh = make_refresh_token(user_doc["id"])
    return {"access_token": access, "refresh_token": refresh, "user": to_user_out(user_doc), "mfa_required": False}


@api.post("/auth/login", response_model=TokenOut)
async def login(payload: LoginIn, request: Request):
    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        await db.login_history.insert_one({
            "id": new_id(), "user_id": user.get("id") if user else None,
            "email": payload.email.lower(), "success": False,
            "ip": get_client_ip(request), "user_agent": request.headers.get("user-agent"),
            "ts": datetime.now(timezone.utc),
        })
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    if user.get("mfa_enabled"):
        if not payload.mfa_token:
            return {"access_token": "", "refresh_token": "", "user": to_user_out(user), "mfa_required": True}
        if not verify_mfa(user.get("mfa_secret", ""), payload.mfa_token):
            raise HTTPException(status_code=401, detail="Invalid MFA code")

    await db.users.update_one({"id": user["id"]}, {"$set": {"last_login_at": datetime.now(timezone.utc)}})
    await db.login_history.insert_one({
        "id": new_id(), "user_id": user["id"], "email": user["email"], "success": True,
        "ip": get_client_ip(request), "user_agent": request.headers.get("user-agent"),
        "ts": datetime.now(timezone.utc),
    })
    await log_audit(db, user["id"], user["email"], "auth.login",
                    resource_type="user", resource_id=user["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    access = make_access_token(user["id"], user["role"])
    refresh = make_refresh_token(user["id"])
    return {"access_token": access, "refresh_token": refresh, "user": to_user_out(user), "mfa_required": False}


@api.post("/auth/refresh", response_model=TokenOut)
async def refresh_token(payload: RefreshIn):
    data = decode_token(payload.refresh_token)
    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    user = await db.users.find_one({"id": data["sub"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=401, detail="User not found or disabled")
    access = make_access_token(user["id"], user["role"])
    refresh = make_refresh_token(user["id"])
    return {"access_token": access, "refresh_token": refresh, "user": to_user_out(user), "mfa_required": False}


@api.post("/auth/logout")
async def logout(request: Request, user=Depends(get_current_user)):
    await log_audit(db, user["id"], user["email"], "auth.logout",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.get("/auth/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return to_user_out(user)


@api.post("/auth/mfa/setup")
async def mfa_setup(user=Depends(get_current_user)):
    secret = generate_mfa_secret()
    uri = mfa_provisioning_uri(secret, user["email"])
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_secret": secret, "mfa_enabled": False}})
    return {"secret": secret, "provisioning_uri": uri}


@api.post("/auth/mfa/verify")
async def mfa_verify(payload: MfaVerifyIn, request: Request, user=Depends(get_current_user)):
    secret = user.get("mfa_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Run /mfa/setup first")
    if not verify_mfa(secret, payload.token):
        raise HTTPException(status_code=401, detail="Invalid code")
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_enabled": True}})
    await log_audit(db, user["id"], user["email"], "auth.mfa_enabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": True}


@api.post("/auth/mfa/disable")
async def mfa_disable(request: Request, user=Depends(get_current_user)):
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_enabled": False, "mfa_secret": None}})
    await log_audit(db, user["id"], user["email"], "auth.mfa_disabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": False}


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

# ---------- Telehealth helpers ----------
DAILY_API_KEY = os.environ.get("DAILY_API_KEY", "")
DAILY_DOMAIN = os.environ.get("DAILY_DOMAIN", "")


async def daily_create_room(room_name: str, enable_recording: bool = False, enable_knocking: bool = True):
    """Create Daily room. Stubbed if no API key."""
    if not DAILY_API_KEY:
        return {
            "name": room_name,
            "url": f"https://stub.daily.local/{room_name}",
            "_stubbed": True,
        }
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(
                "https://api.daily.co/v1/rooms",
                headers={"Authorization": f"Bearer {DAILY_API_KEY}"},
                json={
                    "name": room_name,
                    "privacy": "private",
                    "properties": {
                        "enable_prejoin_ui": True,
                        "enable_knocking": enable_knocking,
                        "enable_chat": True,
                        "enable_screenshare": True,
                        "enable_recording": "cloud" if enable_recording else "off",
                    },
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("Daily create_room failed: %s", e)
        return {"name": room_name, "url": f"https://stub.daily.local/{room_name}", "_stubbed": True, "error": str(e)}


async def daily_meeting_token(room_name: str, is_owner: bool, user_name: str, exp_minutes: int = 120):
    if not DAILY_API_KEY:
        return {"token": f"stub_token_{new_id()[:8]}", "_stubbed": True}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(
                "https://api.daily.co/v1/meeting-tokens",
                headers={"Authorization": f"Bearer {DAILY_API_KEY}"},
                json={
                    "properties": {
                        "room_name": room_name,
                        "is_owner": is_owner,
                        "user_name": user_name,
                        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=exp_minutes)).timestamp()),
                    }
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("Daily token failed: %s", e)
        return {"token": f"stub_token_{new_id()[:8]}", "_stubbed": True, "error": str(e)}


# ---------- Telehealth routes ----------
@api.post("/appointments/{appt_id}/telehealth/room")
async def create_telehealth_room(
    appt_id: str,
    request: Request,
    user=Depends(require_roles("practitioner", "admin", "staff")),
):
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if a.get("telehealth", {}).get("room_url"):
        return a["telehealth"]
    room_name = f"nms-{appt_id[:8]}"
    info = await daily_create_room(room_name, enable_recording=False, enable_knocking=True)
    telehealth = {
        "room_name": info.get("name", room_name),
        "room_url": info.get("url"),
        "waiting_room": True,
        "created_at": datetime.now(timezone.utc),
        "_stubbed": info.get("_stubbed", False),
    }
    await db.appointments.update_one({"id": appt_id}, {"$set": {"telehealth": telehealth, "visit_mode": "telehealth"}})
    await db.integration_log.insert_one({
        "id": new_id(), "service": "daily", "action": "room.create",
        "payload": {"appointment_id": appt_id, "room_name": room_name},
        "_stubbed": telehealth["_stubbed"], "ts": datetime.now(timezone.utc),
    })
    await log_audit(db, user["id"], user["email"], "telehealth.room_create",
                    resource_type="appointment", resource_id=appt_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return telehealth


@api.get("/appointments/{appt_id}/telehealth/token")
async def get_telehealth_token(appt_id: str, request: Request, user=Depends(get_current_user)):
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    # Access gate
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or a["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
        if not a.get("consent_telehealth"):
            raise HTTPException(status_code=403, detail="Telehealth consent required")
    elif user["role"] not in ("practitioner", "admin", "staff"):
        raise HTTPException(status_code=403, detail="Forbidden")

    telehealth = a.get("telehealth") or {}
    if not telehealth.get("room_name"):
        # auto-create
        room_name = f"nms-{appt_id[:8]}"
        info = await daily_create_room(room_name)
        telehealth = {
            "room_name": info.get("name", room_name),
            "room_url": info.get("url"),
            "waiting_room": True,
            "created_at": datetime.now(timezone.utc),
            "_stubbed": info.get("_stubbed", False),
        }
        await db.appointments.update_one({"id": appt_id}, {"$set": {"telehealth": telehealth}})

    is_owner = user["role"] in ("practitioner", "admin", "staff")
    tok = await daily_meeting_token(telehealth["room_name"], is_owner=is_owner, user_name=user.get("full_name") or user["email"])
    await log_audit(db, user["id"], user["email"], "telehealth.token",
                    resource_type="appointment", resource_id=appt_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {
        "room_url": telehealth.get("room_url"),
        "room_name": telehealth.get("room_name"),
        "token": tok.get("token"),
        "is_owner": is_owner,
        "_stubbed": tok.get("_stubbed", False) or telehealth.get("_stubbed", False),
    }


@api.post("/appointments/{appt_id}/telehealth/consent")
async def telehealth_consent(appt_id: str, payload: TelehealthConsentIn, request: Request, user=Depends(get_current_user)):
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or a["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    await db.appointments.update_one({"id": appt_id}, {"$set": {
        "consent_telehealth": True,
        "consent_telehealth_at": datetime.now(timezone.utc),
        "consent_telehealth_signature": payload.signature,
    }})
    await log_audit(db, user["id"], user["email"], "telehealth.consent",
                    resource_type="appointment", resource_id=appt_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/appointments/{appt_id}/telehealth/recording")
async def toggle_recording(appt_id: str, body: dict, user=Depends(require_roles("practitioner", "admin"))):
    """Stubbed start/stop recording."""
    action = (body or {}).get("action", "start")
    await db.integration_log.insert_one({
        "id": new_id(), "service": "daily", "action": f"recording.{action}",
        "payload": {"appointment_id": appt_id}, "_stubbed": not bool(DAILY_API_KEY),
        "ts": datetime.now(timezone.utc),
    })
    return {"ok": True, "action": action, "_stubbed": not bool(DAILY_API_KEY)}


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


# =================== PHASE 4: TREATMENTS / INVENTORY / POS / TRANSACTIONS / TIME CLOCK / FRONT DESK / IMPORT / ACCOUNT ===================

# ---------- Account / Profile ----------
@api.put("/auth/me", response_model=UserOut)
async def update_me(payload: ProfileUpdate, request: Request, user=Depends(get_current_user)):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
        # also keep client doc in sync if exists
        await db.clients.update_many({"user_id": user["id"]}, {"$set": {k: v for k, v in updates.items() if k in ("full_name", "phone")}})
        await log_audit(db, user["id"], user["email"], "account.update",
                        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    u = await db.users.find_one({"id": user["id"]})
    return to_user_out(u)


@api.post("/auth/change-password")
async def change_password(payload: PasswordChange, request: Request, user=Depends(get_current_user)):
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    await db.users.update_one({"id": user["id"]}, {"$set": {"password_hash": hash_password(payload.new_password)}})
    await log_audit(db, user["id"], user["email"], "account.password_change",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


# ---------- Treatments ----------
@api.get("/treatments", response_model=List[TreatmentOut])
async def list_treatments(active_only: bool = False, user=Depends(require_roles("admin", "staff", "practitioner"))):
    q = {"active": True} if active_only else {}
    items = await db.treatments.find(q).sort("name", 1).to_list(500)
    return [_strip_id(i) for i in items]


@api.post("/treatments", response_model=TreatmentOut)
async def create_treatment(payload: TreatmentIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["created_at"] = datetime.now(timezone.utc)
    await db.treatments.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "treatment.create",
                    resource_type="treatment", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/treatments/{tid}", response_model=TreatmentOut)
async def update_treatment(tid: str, payload: TreatmentIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    await db.treatments.update_one({"id": tid}, {"$set": payload.dict()})
    t = await db.treatments.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    await log_audit(db, user["id"], user["email"], "treatment.update",
                    resource_type="treatment", resource_id=tid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(t)


@api.delete("/treatments/{tid}")
async def delete_treatment(tid: str, request: Request, user=Depends(require_roles("admin"))):
    await db.treatments.delete_one({"id": tid})
    await log_audit(db, user["id"], user["email"], "treatment.delete",
                    resource_type="treatment", resource_id=tid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


# ---------- Inventory ----------
@api.get("/inventory", response_model=List[InventoryItemOut])
async def list_inventory(user=Depends(require_roles("admin", "staff"))):
    items = await db.inventory_items.find().sort("name", 1).to_list(500)
    return [_strip_id(i) for i in items]


@api.post("/inventory", response_model=InventoryItemOut)
async def create_inventory(payload: InventoryItemIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["created_at"] = datetime.now(timezone.utc)
    await db.inventory_items.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "inventory.create",
                    resource_type="inventory", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/inventory/{iid}", response_model=InventoryItemOut)
async def update_inventory(iid: str, payload: InventoryItemIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    await db.inventory_items.update_one({"id": iid}, {"$set": payload.dict()})
    item = await db.inventory_items.find_one({"id": iid})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    await log_audit(db, user["id"], user["email"], "inventory.update",
                    resource_type="inventory", resource_id=iid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(item)


@api.post("/inventory/{iid}/adjust", response_model=InventoryItemOut)
async def adjust_inventory(iid: str, payload: InventoryAdjustIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    item = await db.inventory_items.find_one({"id": iid})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    new_stock = (item.get("stock", 0) or 0) + payload.delta
    await db.inventory_items.update_one({"id": iid}, {"$set": {"stock": new_stock}})
    await db.inventory_transactions.insert_one({
        "id": new_id(), "item_id": iid, "change": payload.delta,
        "reason": payload.reason, "note": payload.note,
        "user_id": user["id"], "ts": datetime.now(timezone.utc),
    })
    # Low stock alert (stubbed email)
    if new_stock <= (item.get("low_stock_threshold", 5) or 5):
        await db.integration_log.insert_one({
            "id": new_id(), "service": "sendgrid", "action": "low_stock_alert",
            "payload": {"item_id": iid, "name": item.get("name"), "stock": new_stock},
            "_stubbed": True, "ts": datetime.now(timezone.utc),
        })
    await log_audit(db, user["id"], user["email"], "inventory.adjust",
                    resource_type="inventory", resource_id=iid, metadata={"delta": payload.delta},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    item = await db.inventory_items.find_one({"id": iid})
    return _strip_id(item)


# ---------- POS Checkout & Transactions ----------
async def _hydrate_txn(t):
    t = _strip_id(t)
    if not t:
        return None
    if t.get("client_id"):
        c = await db.clients.find_one({"id": t["client_id"]})
        if c:
            t["client_name"] = c.get("full_name")
    if t.get("created_by"):
        u = await db.users.find_one({"id": t["created_by"]})
        if u:
            t["created_by_name"] = u.get("full_name")
    return t


@api.post("/pos/checkout", response_model=TransactionOut)
async def pos_checkout(payload: PosCheckoutIn, request: Request,
                       user=Depends(require_roles("admin", "staff"))):
    if not payload.lines:
        raise HTTPException(status_code=400, detail="No line items")
    out_lines = []
    subtotal = 0.0
    # Decrement inventory & build out_lines
    for line in payload.lines:
        line_total = round(line.qty * line.unit_price, 2)
        out_lines.append({**line.dict(), "line_total": line_total})
        subtotal += line_total
        if line.type == "inventory" and line.ref_id:
            inv = await db.inventory_items.find_one({"id": line.ref_id})
            if inv:
                new_stock = (inv.get("stock", 0) or 0) - line.qty
                await db.inventory_items.update_one({"id": line.ref_id}, {"$set": {"stock": new_stock}})
                await db.inventory_transactions.insert_one({
                    "id": new_id(), "item_id": line.ref_id, "change": -line.qty,
                    "reason": "pos_sale", "ts": datetime.now(timezone.utc), "user_id": user["id"],
                })
                if new_stock <= (inv.get("low_stock_threshold", 5) or 5):
                    await db.integration_log.insert_one({
                        "id": new_id(), "service": "sendgrid", "action": "low_stock_alert",
                        "payload": {"item_id": line.ref_id, "stock": new_stock},
                        "_stubbed": True, "ts": datetime.now(timezone.utc),
                    })
                    # Push admins/staff
                    admins = await db.users.find({"role": {"$in": ["admin", "staff"]}}).to_list(50)
                    for u in admins:
                        await push_to_user(
                            u["id"],
                            "Low stock alert",
                            f"{inv.get('name','item')} now at {new_stock} (threshold {inv.get('low_stock_threshold',5)})",
                            url="/portal/admin/inventory",
                            tag=f"lowstock-{line.ref_id}",
                        )
    discount = max(0.0, payload.discount or 0.0)
    tip = max(0.0, payload.tip or 0.0)
    after_discount = max(0.0, subtotal - discount)
    tax = round(after_discount * (payload.tax_rate or 0.0), 2)
    total = round(after_discount + tax + tip, 2)

    txn = {
        "id": new_id(),
        "client_id": payload.client_id,
        "lines": out_lines,
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "tip": round(tip, 2),
        "tax": tax,
        "total": total,
        "payment_method": payload.payment_method,
        "payment_ref": payload.payment_ref,
        "status": "paid" if payload.payment_method != "stripe" else "pending",
        "paid_at": datetime.now(timezone.utc) if payload.payment_method != "stripe" else None,
        "note": payload.note,
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc),
    }
    await db.transactions.insert_one(txn)

    # Stripe stub
    if payload.payment_method == "stripe":
        await db.integration_log.insert_one({
            "id": new_id(), "service": "stripe", "action": "checkout_session",
            "payload": {"transaction_id": txn["id"], "amount_cents": int(total * 100)},
            "_stubbed": True, "ts": datetime.now(timezone.utc),
        })

    await log_audit(db, user["id"], user["email"], "pos.checkout",
                    resource_type="transaction", resource_id=txn["id"],
                    metadata={"total": total, "method": payload.payment_method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_txn(txn)


@api.get("/transactions", response_model=List[TransactionOut])
async def list_transactions(client_id: Optional[str] = None, limit: int = 200,
                            user=Depends(require_roles("admin", "staff"))):
    q = {}
    if client_id:
        q["client_id"] = client_id
    items = await db.transactions.find(q).sort("created_at", -1).to_list(min(limit, 500))
    return [await _hydrate_txn(i) for i in items]


@api.get("/transactions/{tid}/receipt")
async def transaction_receipt(tid: str, user=Depends(get_current_user)):
    t = await db.transactions.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or t.get("client_id") != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    # Generate PDF
    buf = _io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    width, _ = letter
    y = 10.5 * inch
    c.setFont("Helvetica-Bold", 16)
    c.drawString(0.75 * inch, y, "Natural Medical Solutions Wellness Center")
    y -= 0.3 * inch
    c.setFont("Helvetica", 10)
    c.drawString(0.75 * inch, y, "1130 Upper Hembree Rd, Roswell, GA 30076")
    y -= 0.2 * inch
    c.drawString(0.75 * inch, y, "(770) 674-6311")
    y -= 0.4 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75 * inch, y, f"Receipt {t['id'][:8]}")
    c.drawRightString(width - 0.75 * inch, y, datetime.now(timezone.utc).strftime("%b %d, %Y"))
    y -= 0.3 * inch
    if t.get("client_id"):
        cl = await db.clients.find_one({"id": t["client_id"]})
        if cl:
            c.setFont("Helvetica", 10)
            c.drawString(0.75 * inch, y, f"Client: {cl.get('full_name', '')}")
            y -= 0.25 * inch
    c.line(0.75 * inch, y, width - 0.75 * inch, y)
    y -= 0.2 * inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y, "Item")
    c.drawString(4.5 * inch, y, "Qty")
    c.drawString(5.2 * inch, y, "Unit")
    c.drawRightString(width - 0.75 * inch, y, "Total")
    y -= 0.2 * inch
    c.setFont("Helvetica", 10)
    for line in t.get("lines", []):
        c.drawString(0.75 * inch, y, line["name"][:60])
        c.drawString(4.5 * inch, y, str(line["qty"]))
        c.drawString(5.2 * inch, y, f"${line['unit_price']:.2f}")
        c.drawRightString(width - 0.75 * inch, y, f"${line['line_total']:.2f}")
        y -= 0.2 * inch
    y -= 0.1 * inch
    c.line(0.75 * inch, y, width - 0.75 * inch, y)
    y -= 0.25 * inch
    for label, val in [("Subtotal", t["subtotal"]), ("Discount", -t.get("discount", 0)),
                       ("Tax", t.get("tax", 0)), ("Tip", t.get("tip", 0))]:
        if val:
            c.drawRightString(width - 1.5 * inch, y, label)
            c.drawRightString(width - 0.75 * inch, y, f"${val:.2f}")
            y -= 0.18 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(width - 1.5 * inch, y, "TOTAL")
    c.drawRightString(width - 0.75 * inch, y, f"${t['total']:.2f}")
    y -= 0.25 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.75 * inch, y, f"Paid via {t['payment_method'].replace('_', ' ').title()}")
    y -= 0.4 * inch
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(0.75 * inch, y, "Thank you for choosing Natural Medical Solutions.")
    c.showPage()
    c.save()
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="receipt-{t["id"][:8]}.pdf"'})


# ---------- Time Clock ----------
def _calc_minutes(entry):
    if not entry.get("clock_in") or not entry.get("clock_out"):
        return None
    total = (entry["clock_out"] - entry["clock_in"]).total_seconds() / 60
    for b in entry.get("breaks", []) or []:
        if b.get("start") and b.get("end"):
            total -= (b["end"] - b["start"]).total_seconds() / 60
    return round(total, 1)


async def _hydrate_time(e):
    e = _strip_id(e)
    if not e:
        return None
    u = await db.users.find_one({"id": e["user_id"]})
    if u:
        e["user_name"] = u.get("full_name")
    e["total_minutes"] = _calc_minutes(e)
    return e


@api.post("/time-clock/punch-in", response_model=TimeEntryOut)
async def punch_in(user=Depends(require_roles("admin", "staff", "practitioner"))):
    open_e = await db.time_entries.find_one({"user_id": user["id"], "clock_out": None})
    if open_e:
        return await _hydrate_time(open_e)
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "clock_in": datetime.now(timezone.utc),
        "clock_out": None,
        "breaks": [],
        "note": None,
    }
    await db.time_entries.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "timeclock.in", resource_type="time_entry", resource_id=doc["id"])
    return await _hydrate_time(doc)


@api.post("/time-clock/punch-out", response_model=TimeEntryOut)
async def punch_out(user=Depends(require_roles("admin", "staff", "practitioner"))):
    e = await db.time_entries.find_one({"user_id": user["id"], "clock_out": None})
    if not e:
        raise HTTPException(status_code=400, detail="Not punched in")
    # auto-close any open break
    breaks = e.get("breaks") or []
    if breaks and not breaks[-1].get("end"):
        breaks[-1]["end"] = datetime.now(timezone.utc)
    await db.time_entries.update_one({"id": e["id"]}, {"$set": {"clock_out": datetime.now(timezone.utc), "breaks": breaks}})
    e = await db.time_entries.find_one({"id": e["id"]})
    await log_audit(db, user["id"], user["email"], "timeclock.out", resource_type="time_entry", resource_id=e["id"])
    return await _hydrate_time(e)


@api.post("/time-clock/break-start", response_model=TimeEntryOut)
async def break_start(user=Depends(require_roles("admin", "staff", "practitioner"))):
    e = await db.time_entries.find_one({"user_id": user["id"], "clock_out": None})
    if not e:
        raise HTTPException(status_code=400, detail="Punch in first")
    breaks = e.get("breaks") or []
    if breaks and not breaks[-1].get("end"):
        return await _hydrate_time(e)  # already on break
    breaks.append({"start": datetime.now(timezone.utc), "end": None})
    await db.time_entries.update_one({"id": e["id"]}, {"$set": {"breaks": breaks}})
    e = await db.time_entries.find_one({"id": e["id"]})
    return await _hydrate_time(e)


@api.post("/time-clock/break-end", response_model=TimeEntryOut)
async def break_end(user=Depends(require_roles("admin", "staff", "practitioner"))):
    e = await db.time_entries.find_one({"user_id": user["id"], "clock_out": None})
    if not e:
        raise HTTPException(status_code=400, detail="Not on a shift")
    breaks = e.get("breaks") or []
    if not breaks or breaks[-1].get("end"):
        return await _hydrate_time(e)
    breaks[-1]["end"] = datetime.now(timezone.utc)
    await db.time_entries.update_one({"id": e["id"]}, {"$set": {"breaks": breaks}})
    e = await db.time_entries.find_one({"id": e["id"]})
    return await _hydrate_time(e)


@api.get("/time-clock/me", response_model=List[TimeEntryOut])
async def my_time_entries(limit: int = 50, user=Depends(require_roles("admin", "staff", "practitioner"))):
    items = await db.time_entries.find({"user_id": user["id"]}).sort("clock_in", -1).to_list(min(limit, 200))
    return [await _hydrate_time(i) for i in items]


@api.get("/time-clock/all", response_model=List[TimeEntryOut])
async def all_time_entries(user=Depends(require_roles("admin"))):
    items = await db.time_entries.find().sort("clock_in", -1).to_list(500)
    return [await _hydrate_time(i) for i in items]


@api.put("/time-clock/{eid}", response_model=TimeEntryOut)
async def edit_time(eid: str, payload: TimeEditIn, request: Request, user=Depends(require_roles("admin"))):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if updates:
        updates["edited_by"] = user["id"]
        await db.time_entries.update_one({"id": eid}, {"$set": updates})
    e = await db.time_entries.find_one({"id": eid})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    await log_audit(db, user["id"], user["email"], "timeclock.edit", resource_type="time_entry", resource_id=eid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_time(e)


# ---------- Front Desk ----------
async def _hydrate_fd(v):
    v = _strip_id(v)
    if not v:
        return None
    c = await db.clients.find_one({"id": v["client_id"]})
    if c:
        v["client_name"] = c.get("full_name")
    return v


@api.get("/front-desk/today", response_model=List[FrontDeskOut])
async def front_desk_today(user=Depends(require_roles("admin", "staff", "practitioner"))):
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    items = await db.front_desk_visits.find({"created_at": {"$gte": start, "$lt": end}}).sort("created_at", 1).to_list(200)
    return [await _hydrate_fd(i) for i in items]


@api.post("/front-desk/check-in", response_model=FrontDeskOut)
async def front_desk_checkin(payload: FrontDeskCheckIn, request: Request,
                             user=Depends(require_roles("admin", "staff", "practitioner"))):
    c = await db.clients.find_one({"id": payload.client_id})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    doc = {
        "id": new_id(),
        "client_id": payload.client_id,
        "appointment_id": payload.appointment_id,
        "walk_in": payload.walk_in,
        "status": "checked_in",
        "room": payload.room,
        "checked_in_at": datetime.now(timezone.utc),
        "checked_out_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    await db.front_desk_visits.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "frontdesk.check_in",
                    resource_type="visit", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_fd(doc)


@api.put("/front-desk/{vid}", response_model=FrontDeskOut)
async def front_desk_update(vid: str, payload: FrontDeskUpdate, request: Request,
                            user=Depends(require_roles("admin", "staff", "practitioner"))):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if payload.status == "checked_out":
        updates["checked_out_at"] = datetime.now(timezone.utc)
    await db.front_desk_visits.update_one({"id": vid}, {"$set": updates})
    v = await db.front_desk_visits.find_one({"id": vid})
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    await log_audit(db, user["id"], user["email"], "frontdesk.update",
                    resource_type="visit", resource_id=vid, metadata=updates,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_fd(v)


# ---------- Import Clients (CSV) ----------
@api.post("/clients/import")
async def import_clients(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_roles("admin")),
):
    raw = await file.read()
    try:
        reader = csv.DictReader(_io.StringIO(raw.decode("utf-8-sig")))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
    imported = 0
    skipped = 0
    errors = []
    for row in reader:
        full_name = (row.get("full_name") or row.get("name") or "").strip()
        email = (row.get("email") or "").strip().lower() or None
        if not full_name and not email:
            skipped += 1
            errors.append({"row": row, "reason": "missing name/email"})
            continue
        # dedupe by email if present
        if email and await db.clients.find_one({"email": email}):
            skipped += 1
            continue
        doc = {
            "id": new_id(),
            "user_id": None,
            "full_name": full_name or email,
            "email": email,
            "phone": (row.get("phone") or "").strip() or None,
            "dob": (row.get("dob") or "").strip() or None,
            "sex": (row.get("sex") or "").strip() or None,
            "address": (row.get("address") or "").strip() or None,
            "emergency_contact": (row.get("emergency_contact") or "").strip() or None,
            "intake_completed": False,
            "created_at": datetime.now(timezone.utc),
        }
        await db.clients.insert_one(doc)
        imported += 1
    await db.imported_batches.insert_one({
        "id": new_id(), "filename": file.filename,
        "imported": imported, "skipped": skipped,
        "by_user": user["id"], "ts": datetime.now(timezone.utc),
    })
    await log_audit(db, user["id"], user["email"], "clients.import",
                    metadata={"imported": imported, "skipped": skipped, "filename": file.filename},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"imported": imported, "skipped": skipped, "errors": errors[:10]}



# ---------- Provider Analytics ----------
@api.get("/analytics/overview")
async def analytics_overview(
    days: int = 30,
    user=Depends(require_roles("practitioner", "admin", "staff")),
):
    """KPI overview for the practice (last N days)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    # Revenue from transactions
    txns = await db.transactions.find({
        "status": "paid",
        "created_at": {"$gte": start, "$lt": end},
    }).to_list(2000)
    total_revenue = round(sum(t.get("total", 0) for t in txns), 2)
    revenue_by_method = {}
    for t in txns:
        m = t.get("payment_method", "other")
        revenue_by_method[m] = round(revenue_by_method.get(m, 0) + (t.get("total", 0) or 0), 2)

    # Daily revenue series
    by_day = {}
    for t in txns:
        d = t["created_at"].date().isoformat()
        by_day[d] = round(by_day.get(d, 0) + (t.get("total", 0) or 0), 2)
    revenue_series = [{"date": d, "revenue": by_day[d]} for d in sorted(by_day)]

    # Appointments
    appts = await db.appointments.find({
        "start_time": {"$gte": start, "$lt": end},
    }).to_list(2000)
    no_show = [a for a in appts if a.get("status") == "no_show"]
    completed = [a for a in appts if a.get("status") in ("completed", "checked_out")]
    avg_duration = 0
    if completed:
        durations = []
        for a in completed:
            if a.get("start_time") and a.get("end_time"):
                durations.append((a["end_time"] - a["start_time"]).total_seconds() / 60)
        if durations:
            avg_duration = round(sum(durations) / len(durations), 1)

    # Top treatments by line revenue
    line_rev = {}
    line_count = {}
    for t in txns:
        for line in t.get("lines", []) or []:
            if line.get("type") == "treatment":
                key = line.get("name", "Unknown")
                line_rev[key] = round(line_rev.get(key, 0) + (line.get("line_total", 0) or 0), 2)
                line_count[key] = line_count.get(key, 0) + (line.get("qty", 1) or 1)
    top_treatments = sorted(
        [{"name": k, "revenue": line_rev[k], "count": line_count.get(k, 0)} for k in line_rev],
        key=lambda x: x["revenue"], reverse=True
    )[:8]

    # New clients in window
    new_clients = await db.clients.count_documents({"created_at": {"$gte": start, "$lt": end}})

    # Active practitioners (with >=1 note in window)
    notes = await db.visit_notes.find({"created_at": {"$gte": start, "$lt": end}}).to_list(2000)
    by_provider = {}
    for n in notes:
        pid = n.get("provider_id") or "unknown"
        by_provider[pid] = by_provider.get(pid, 0) + 1
    # single $in lookup instead of N+1
    pids = [pid for pid in by_provider.keys() if pid != "unknown"]
    users_map = {}
    if pids:
        async for u in db.users.find({"id": {"$in": pids}}, {"_id": 0, "id": 1, "full_name": 1}):
            users_map[u["id"]] = u.get("full_name")
    notes_by_provider = []
    for pid, cnt in sorted(by_provider.items(), key=lambda x: x[1], reverse=True):
        notes_by_provider.append({
            "provider_id": pid,
            "provider_name": users_map.get(pid, pid),
            "notes": cnt,
        })

    # Inventory low-stock count
    inv = await db.inventory_items.find().to_list(500)
    low_stock = [i for i in inv if (i.get("stock", 0) or 0) <= (i.get("low_stock_threshold", 5) or 5)]

    return {
        "window_days": days,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "revenue": {
            "total": total_revenue,
            "by_method": revenue_by_method,
            "series": revenue_series,
        },
        "appointments": {
            "total": len(appts),
            "completed": len(completed),
            "no_shows": len(no_show),
            "no_show_rate": round((len(no_show) / len(appts) * 100), 1) if appts else 0,
            "avg_duration_min": avg_duration,
        },
        "clients": {"new_clients": new_clients},
        "top_treatments": top_treatments,
        "notes_by_provider": notes_by_provider[:10],
        "low_stock_items": len(low_stock),
    }


# ---------- End-of-Day Cash Drawer Report (PDF) ----------
@api.get("/reports/eod-cash-drawer")
async def eod_cash_drawer(user=Depends(require_roles("admin", "staff"))):
    """One-page PDF: today's revenue by method, top treatments, low-stock items."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    txns = await db.transactions.find({
        "status": "paid", "created_at": {"$gte": start, "$lt": now},
    }).to_list(2000)

    revenue_by_method = {}
    total = 0.0
    line_rev = {}
    line_count = {}
    for t in txns:
        m = t.get("payment_method", "other")
        revenue_by_method[m] = round(revenue_by_method.get(m, 0) + (t.get("total", 0) or 0), 2)
        total += t.get("total", 0) or 0
        for line in t.get("lines", []) or []:
            key = line.get("name", "Unknown")
            line_rev[key] = round(line_rev.get(key, 0) + (line.get("line_total", 0) or 0), 2)
            line_count[key] = line_count.get(key, 0) + (line.get("qty", 1) or 1)
    total = round(total, 2)
    top_items = sorted(
        [{"name": k, "qty": line_count.get(k, 0), "revenue": line_rev[k]} for k in line_rev],
        key=lambda x: x["revenue"], reverse=True
    )[:10]

    inv = await db.inventory_items.find().to_list(500)
    low = sorted(
        [i for i in inv if (i.get("stock", 0) or 0) <= (i.get("low_stock_threshold", 5) or 5)],
        key=lambda x: x.get("stock", 0)
    )

    METHOD = {
        "chase_pos": "Chase POS", "cash": "Cash", "check": "Check",
        "card_other": "Card", "stripe": "Stripe",
    }

    buf = _io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    width, _ = letter
    y = 10.5 * inch
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.75 * inch, y, "Natural Medical Solutions Wellness Center")
    y -= 0.3 * inch
    c.setFont("Helvetica", 10)
    c.drawString(0.75 * inch, y, "End-of-Day Cash Drawer Report")
    c.drawRightString(width - 0.75 * inch, y, now.strftime("%A, %b %d %Y · %I:%M %p UTC"))
    y -= 0.4 * inch
    c.line(0.75 * inch, y, width - 0.75 * inch, y)
    y -= 0.3 * inch

    # Revenue summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75 * inch, y, f"Today's revenue ({len(txns)} transactions)")
    y -= 0.25 * inch
    c.setFont("Helvetica", 10)
    for m, val in sorted(revenue_by_method.items(), key=lambda x: -x[1]):
        c.drawString(1.0 * inch, y, METHOD.get(m, m.replace("_", " ").title()))
        c.drawRightString(width - 0.75 * inch, y, f"${val:.2f}")
        y -= 0.2 * inch
    y -= 0.05 * inch
    c.line(1.0 * inch, y, width - 0.75 * inch, y)
    y -= 0.2 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.0 * inch, y, "TOTAL")
    c.drawRightString(width - 0.75 * inch, y, f"${total:.2f}")
    y -= 0.45 * inch

    # Cash variance line for staff to fill in
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y, "Drawer reconciliation")
    y -= 0.25 * inch
    c.setFont("Helvetica", 9)
    c.drawString(1.0 * inch, y, f"Cash expected:  ${revenue_by_method.get('cash', 0):.2f}")
    y -= 0.2 * inch
    c.drawString(1.0 * inch, y, "Cash counted:   $ ____________")
    y -= 0.2 * inch
    c.drawString(1.0 * inch, y, "Variance:       $ ____________")
    y -= 0.2 * inch
    c.drawString(1.0 * inch, y, "Closed by: ______________________   Initials: _______")
    y -= 0.4 * inch

    # Top items
    if top_items:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(0.75 * inch, y, "Top items today")
        y -= 0.25 * inch
        c.setFont("Helvetica-Bold", 9)
        c.drawString(1.0 * inch, y, "Item")
        c.drawString(4.5 * inch, y, "Qty")
        c.drawRightString(width - 0.75 * inch, y, "Revenue")
        y -= 0.2 * inch
        c.setFont("Helvetica", 9)
        for it in top_items:
            c.drawString(1.0 * inch, y, it["name"][:55])
            c.drawString(4.5 * inch, y, str(it["qty"]))
            c.drawRightString(width - 0.75 * inch, y, f"${it['revenue']:.2f}")
            y -= 0.2 * inch
        y -= 0.2 * inch

    # Low stock
    if low and y > 1.5 * inch:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(0.75 * inch, y, f"Low-stock items ({len(low)})")
        y -= 0.25 * inch
        c.setFont("Helvetica", 9)
        for i in low[:15]:
            c.drawString(1.0 * inch, y,
                         f"{i.get('name','—')[:50]} — stock {i.get('stock', 0)} (threshold {i.get('low_stock_threshold', 5)})")
            y -= 0.18 * inch
            if y < 1.0 * inch:
                break

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(0.75 * inch, 0.5 * inch,
                 "Confidential · Generated by NatMedSol Portal · Demo environment")

    c.showPage()
    c.save()
    buf.seek(0)
    await log_audit(db, user["id"], user["email"], "report.eod_cash_drawer")
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="eod-cash-drawer-{now.date().isoformat()}.pdf"'})


# ---------- Self-hosted WebRTC visit signaling (WebSocket) ----------
from fastapi import WebSocket, WebSocketDisconnect

# Active sessions: {appt_id: {role: WebSocket}}
_visit_rooms = {}

@api.websocket("/ws/visit/{appt_id}")
async def ws_visit(websocket: WebSocket, appt_id: str,
                    token: Optional[str] = Query(None),
                    ticket: Optional[str] = Query(None)):
    """WebRTC signaling + chat relay. Auth via one-shot ticket (preferred) or JWT token (legacy)."""
    u = None
    if ticket:
        # One-shot ticket — burned on first use
        t = await db.ws_tickets.find_one_and_update(
            {"ticket": ticket, "appointment_id": appt_id, "used": False,
             "expires_at": {"$gte": datetime.now(timezone.utc)}},
            {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}},
        )
        if not t:
            await websocket.close(code=4401)
            return
        u = await db.users.find_one({"id": t["user_id"]})
    elif token:
        try:
            payload = decode_token(token)
            u = await db.users.find_one({"id": payload.get("sub")})
        except Exception:
            await websocket.close(code=4401)
            return
    if not u:
        await websocket.close(code=4401)
        return

    appt = await db.appointments.find_one({"id": appt_id})
    if not appt:
        await websocket.close(code=4404)
        return

    role = "provider" if u["role"] in ("practitioner", "admin", "staff") else "client"
    if role == "client":
        sc = await _resolve_self_client(u)
        if not sc or appt.get("client_id") != sc["id"]:
            await websocket.close(code=4403)
            return

    await websocket.accept()
    room = _visit_rooms.setdefault(appt_id, {})
    # If a participant of the same role is already connected, close the old one
    if room.get(role):
        try:
            await room[role].close(code=4000)
        except Exception:
            pass
    room[role] = websocket

    # Tell both peers about presence
    other_role = "client" if role == "provider" else "provider"
    if room.get(other_role):
        try:
            await room[other_role].send_json({"type": "peer-joined", "role": role})
        except Exception:
            pass
    await websocket.send_json({"type": "joined", "role": role,
                               "peer_present": bool(room.get(other_role))})

    # Audit join
    await log_audit(db, u["id"], u["email"], "telehealth.ws_join",
                    resource_type="appointment", resource_id=appt_id,
                    metadata={"role": role})

    try:
        while True:
            data = await websocket.receive_json()
            t = data.get("type")
            # Messages we relay to the other peer: webrtc-offer, webrtc-answer, ice-candidate, chat
            if t in ("webrtc-offer", "webrtc-answer", "ice-candidate", "chat",
                     "media-state", "screen-share"):
                peer_ws = room.get(other_role)
                if peer_ws:
                    try:
                        await peer_ws.send_json({**data, "from": role})
                    except Exception:
                        pass
                if t == "chat":
                    # persist chat
                    await db.visit_chat.insert_one({
                        "id": new_id(), "appointment_id": appt_id,
                        "from_user": u["id"], "from_role": role,
                        "body": data.get("body", "")[:2000],
                        "ts": datetime.now(timezone.utc),
                    })
            elif t == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("ws_visit error: %s", e)
    finally:
        if room.get(role) is websocket:
            room.pop(role, None)
        peer_ws = room.get(other_role)
        if peer_ws:
            try:
                await peer_ws.send_json({"type": "peer-left", "role": role})
            except Exception:
                pass
        if not room:
            _visit_rooms.pop(appt_id, None)
        await log_audit(db, u["id"], u["email"], "telehealth.ws_leave",
                        resource_type="appointment", resource_id=appt_id,
                        metadata={"role": role})


@api.get("/visits/{appt_id}/chat")
async def visit_chat_history(appt_id: str, user=Depends(get_current_user)):
    """Recent chat history for a visit (self-hosted)."""
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or a.get("client_id") != sc["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    msgs = await db.visit_chat.find({"appointment_id": appt_id}).sort("ts", 1).to_list(500)
    return [_strip_id(m) for m in msgs]


# ---------- Visit recording upload (chunked WebM to GridFS) ----------
@api.post("/visits/{appt_id}/recording")
async def upload_visit_recording(
    appt_id: str,
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_roles("practitioner", "admin", "staff")),
):
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    contents = await file.read()
    file_id = await fs_bucket.upload_from_stream(
        f"visit-{appt_id}-{int(datetime.now(timezone.utc).timestamp())}.webm",
        contents,
        metadata={"appointment_id": appt_id, "uploader_id": user["id"], "kind": "visit_recording"},
    )
    fid = str(file_id)
    await db.appointments.update_one({"id": appt_id}, {"$push": {"recordings": {
        "file_id": fid, "size": len(contents), "uploaded_by": user["id"],
        "ts": datetime.now(timezone.utc),
    }}})
    await log_audit(db, user["id"], user["email"], "telehealth.recording_upload",
                    resource_type="appointment", resource_id=appt_id,
                    metadata={"size": len(contents)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"file_id": fid, "size": len(contents)}


@api.get("/visits/{appt_id}/recordings")
async def list_visit_recordings(appt_id: str, user=Depends(get_current_user)):
    """List recordings attached to an appointment."""
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or a.get("client_id") != sc["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    out = []
    for r in (a.get("recordings") or []):
        out.append({
            "file_id": r.get("file_id"),
            "size": r.get("size"),
            "ts": r.get("ts"),
            "uploaded_by": r.get("uploaded_by"),
            "download_url": f"/api/visits/{appt_id}/recordings/{r.get('file_id')}",
        })
    return out


@api.get("/visits/{appt_id}/recordings/{file_id}")
async def download_visit_recording(appt_id: str, file_id: str, request: Request,
                                   user=Depends(get_current_user)):
    """Stream a recorded visit WebM from GridFS. RBAC: client may only access their own."""
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or a.get("client_id") != sc["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    # Confirm file is bound to this appointment via metadata
    try:
        oid = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file id")
    found = None
    for r in (a.get("recordings") or []):
        if r.get("file_id") == file_id:
            found = r
            break
    if not found:
        raise HTTPException(status_code=404, detail="Recording not found")
    try:
        stream = await fs_bucket.open_download_stream(oid)
    except Exception:
        raise HTTPException(status_code=404, detail="Recording not found in GridFS")
    await log_audit(db, user["id"], user["email"], "telehealth.recording_download",
                    resource_type="appointment", resource_id=appt_id,
                    metadata={"file_id": file_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    async def _iter():
        while True:
            chunk = await stream.readchunk()
            if not chunk:
                break
            yield chunk

    return StreamingResponse(_iter(), media_type="video/webm",
                             headers={"Content-Disposition": f'attachment; filename="visit-{appt_id}.webm"'})


# ---------- WS auth hardening: one-shot signed handshake ticket ----------
import secrets as _secrets

@api.post("/visits/{appt_id}/ws-ticket")
async def issue_ws_ticket(appt_id: str, user=Depends(get_current_user)):
    """Issue a one-shot ticket (60s TTL) so the WebSocket handshake never carries a JWT."""
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or a.get("client_id") != sc["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    ticket = _secrets.token_urlsafe(32)
    await db.ws_tickets.insert_one({
        "ticket": ticket, "appointment_id": appt_id,
        "user_id": user["id"], "user_role": user["role"],
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
        "used": False,
    })
    return {"ticket": ticket, "expires_in": 60}


# ---------- WebRTC ICE config (STUN + optional TURN) ----------
@api.get("/webrtc/config")
async def webrtc_config(user=Depends(get_current_user)):
    """Return ICE servers — STUN public + optional self-hosted coturn from env."""
    servers = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
    ]
    turn_url = os.environ.get("TURN_URL")
    if turn_url:
        entry = {"urls": turn_url}
        if os.environ.get("TURN_USERNAME"):
            entry["username"] = os.environ["TURN_USERNAME"]
        if os.environ.get("TURN_PASSWORD"):
            entry["credential"] = os.environ["TURN_PASSWORD"]
        servers.append(entry)
    return {"iceServers": servers}


# ---------- In-call SOAP autosave (provider-only) ----------
@api.put("/visits/{appt_id}/live-soap")
async def save_live_soap(appt_id: str, payload: dict,
                          user=Depends(require_roles("practitioner", "admin"))):
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    update = {
        "appointment_id": appt_id,
        "client_id": a.get("client_id"),
        "provider_id": user["id"],
        "subjective": payload.get("subjective", ""),
        "objective": payload.get("objective", ""),
        "assessment": payload.get("assessment", ""),
        "plan": payload.get("plan", ""),
        "updated_at": datetime.now(timezone.utc),
    }
    await db.live_soap_drafts.update_one(
        {"appointment_id": appt_id, "provider_id": user["id"]},
        {"$set": update, "$setOnInsert": {"id": new_id(), "created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {"saved_at": update["updated_at"].isoformat()}


@api.get("/visits/{appt_id}/live-soap")
async def get_live_soap(appt_id: str, user=Depends(require_roles("practitioner", "admin"))):
    d = await db.live_soap_drafts.find_one({"appointment_id": appt_id, "provider_id": user["id"]})
    return _strip_id(d) if d else {"subjective": "", "objective": "", "assessment": "", "plan": ""}


# ---------- Auto-draft visit summary from chat transcript ----------
@api.post("/visits/{appt_id}/auto-draft")
async def auto_draft_summary(appt_id: str, user=Depends(require_roles("practitioner", "admin"))):
    """Stitch chat transcript into a SOAP-shaped draft (rule-based, no LLM)."""
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    msgs = await db.visit_chat.find({"appointment_id": appt_id}).sort("ts", 1).to_list(500)
    client_lines = [m.get("body", "") for m in msgs if m.get("from_role") == "client"]
    provider_lines = [m.get("body", "") for m in msgs if m.get("from_role") == "provider"]
    subjective = " ".join(client_lines)[:2000]
    objective = "Telehealth visit · video and audio established · provider observed client throughout the visit."
    assessment = " ".join(provider_lines[: max(1, len(provider_lines) // 2)])[:1500]
    plan = " ".join(provider_lines[max(1, len(provider_lines) // 2):])[:1500]
    return {
        "subjective": subjective or "Client reported concerns during telehealth visit.",
        "objective": objective,
        "assessment": assessment or "Pending provider assessment.",
        "plan": plan or "Plan to be finalized by provider.",
        "source": "chat_transcript",
        "message_count": len(msgs),
    }


# ---------- LLM-assisted SOAP draft (Claude Sonnet 4.5 via Emergent LLM Key) ----------
@api.post("/visits/{appt_id}/llm-soap")
async def llm_soap_draft(appt_id: str, user=Depends(require_roles("practitioner", "admin"))):
    """Use Claude Sonnet 4.5 to draft a SOAP note from intake + last note + chat."""
    a = await db.appointments.find_one({"id": appt_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    client = await db.clients.find_one({"id": a.get("client_id")})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    intake = await db.intakes.find_one({"client_id": client["id"]}, sort=[("created_at", -1)]) or {}
    last_note = await db.visit_notes.find_one(
        {"client_id": client["id"]}, sort=[("created_at", -1)]
    )
    msgs = await db.visit_chat.find({"appointment_id": appt_id}).sort("ts", 1).to_list(500)
    transcript = "\n".join(
        f"[{m.get('from_role','?')}] {m.get('body','')}" for m in msgs
    )[:6000]

    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM key not configured")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        sys_msg = (
            "You are a clinical-documentation assistant helping a wellness practitioner "
            "draft a SOAP note from a telehealth visit. Output STRICT JSON with keys "
            "'subjective','objective','assessment','plan'. Keep each <250 words. "
            "Avoid medical diagnoses; this is a wellness setting. Never invent vitals you weren't told."
        )
        client_summary = (
            f"Client: {client.get('full_name','')} (MRN {client.get('mrn','')}). "
            f"Pronouns: {client.get('pronouns','—')}. "
            f"Primary concern: {client.get('primary_concern','—')}. "
            f"Wellness goals: {client.get('wellness_goals','—')}. "
            f"Allergies: {client.get('allergies','—')}. "
            f"Current supplements: {client.get('current_supplements','—')}."
        )
        intake_summary = ""
        if intake:
            intake_summary = "Recent intake answers:\n" + "\n".join(
                f"- {k}: {v}" for k, v in (intake.get("answers") or {}).items()
            )[:1500]
        last_summary = ""
        if last_note:
            last_summary = (
                "Previous SOAP note:\n"
                f"S: {last_note.get('subjective','')[:400]}\n"
                f"A: {last_note.get('assessment','')[:400]}\n"
                f"P: {last_note.get('plan','')[:400]}"
            )
        prompt = f"""{client_summary}

{intake_summary}

{last_summary}

In-call chat transcript:
{transcript or '(no chat messages were exchanged)'}

Produce a SOAP draft as STRICT JSON only — no commentary."""
        chat = LlmChat(
            api_key=api_key,
            session_id=f"soap-{appt_id}",
            system_message=sys_msg,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        response = await chat.send_message(UserMessage(text=prompt))
        # Robust JSON extraction
        import json as _json
        import re as _re
        m = _re.search(r"\{.*\}", response, _re.DOTALL)
        data = _json.loads(m.group(0)) if m else {}
        return {
            "subjective": data.get("subjective", "")[:4000],
            "objective": data.get("objective", "")[:4000],
            "assessment": data.get("assessment", "")[:4000],
            "plan": data.get("plan", "")[:4000],
            "source": "llm",
            "model": "claude-sonnet-4-5-20250929",
        }
    except Exception as e:
        logger.warning("LLM SOAP draft failed: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")


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
import httpx as _httpx

@api.post("/auth/google/session")
async def google_session_exchange(request: Request):
    """Exchange Emergent Auth session_id (header X-Session-ID) for our internal JWT."""
    session_id = request.headers.get("X-Session-ID") or request.headers.get("x-session-id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-ID header")
    async with _httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": session_id},
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Auth provider unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    data = r.json()
    email = (data.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="No email returned by auth provider")

    user = await db.users.find_one({"email": email})
    if not user:
        # Auto-create new client account
        user = {
            "id": new_id(),
            "email": email,
            "full_name": data.get("name") or email.split("@")[0],
            "role": "client",
            "active": True,
            "auth_provider": "google",
            "picture_url": data.get("picture"),
            "created_at": datetime.now(timezone.utc),
        }
        await db.users.insert_one(user)
        # also create a Clients row so /clients/me works
        await db.clients.insert_one({
            "id": new_id(), "user_id": user["id"],
            "full_name": user["full_name"], "email": email,
            "intake_completed": False,
            "created_at": datetime.now(timezone.utc),
        })
    elif not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    else:
        # Update profile picture / link google
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"auth_provider": "google", "picture_url": data.get("picture")}},
        )

    access = make_access_token(user["id"], user["role"])
    refresh = make_refresh_token(user["id"])
    await log_audit(db, user["id"], user["email"], "auth.login_google",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user.get("full_name"),
            "role": user["role"],
            "picture_url": user.get("picture_url"),
        },
    }


# =================== PHASE 10: FORMS & CONSENTS ===================


def _hydrate_template(t: dict) -> dict:
    return _strip_id(t)


def _extract_text_from_upload(filename: str, data: bytes) -> str:
    """Extract text from PDF or DOCX bytes for AI transcription."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(data))
            text = "\n\n".join((p.extract_text() or "") for p in reader.pages)
            return text.strip()
        except Exception as e:
            logger.warning("PDF parse failed: %s", e)
            raise HTTPException(status_code=400, detail=f"Could not parse PDF: {e}")
    if name.endswith(".docx"):
        try:
            from docx import Document as _Docx
            doc = _Docx(io.BytesIO(data))
            paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    paras.append(" | ".join(c.text.strip() for c in row.cells if c.text))
            return "\n".join(paras).strip()
        except Exception as e:
            logger.warning("DOCX parse failed: %s", e)
            raise HTTPException(status_code=400, detail=f"Could not parse DOCX: {e}")
    if name.endswith(".txt"):
        try:
            return data.decode("utf-8", errors="ignore").strip()
        except Exception:
            raise HTTPException(status_code=400, detail="Could not decode text file")
    raise HTTPException(status_code=400, detail="Unsupported file type. Upload PDF, DOCX, or TXT.")


async def _llm_form_transcribe(text: str, hint_category: Optional[str] = None) -> dict:
    """Use Claude 4.5 to convert raw form text into our structured form schema."""
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM key not configured")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"emergentintegrations unavailable: {e}")

    sys_msg = (
        "You are a healthcare-forms transcription assistant. Convert the supplied "
        "consent or intake form text into a STRICT JSON object that our app can render. "
        "Output JSON only — no commentary, no markdown.\n\n"
        "Schema:\n"
        "{\n"
        '  "title": "short title",\n'
        '  "description": "1–2 sentence summary",\n'
        '  "category": "consent|intake|hipaa|photo_release|treatment|other",\n'
        '  "fields": [\n'
        '    {"id": "kebab-case", "type": "text|textarea|date|checkbox|radio|select|signature|email|phone|number",\n'
        '     "label": "Question label", "required": true|false, "placeholder": "...", "options": ["..."], "help_text": "..."}\n'
        "  ]\n"
        "}\n\n"
        "Rules: Always include a final {type:'signature', label:'Patient signature', required:true} field. "
        "If the form requests a printed name + date, add text + date fields above the signature. "
        "Convert checkboxes to type 'checkbox'. Multi-choice lists become type 'radio' with options array. "
        "Detect the category from content (HIPAA notice → 'hipaa'; photo/likeness → 'photo_release'; "
        "treatment/procedure consent → 'treatment'; medical-history forms → 'intake'; otherwise 'consent' or 'other'). "
        "IDs should be kebab-case derived from labels. Limit to 30 fields max."
    )
    if hint_category:
        sys_msg += f"\nUser category hint: {hint_category}."

    chat = LlmChat(
        api_key=api_key,
        session_id=f"form-transcribe-{new_id()[:8]}",
        system_message=sys_msg,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    user = UserMessage(text=f"Form source text:\n\n{text[:18000]}")
    response = await chat.send_message(user)

    import re as _re
    m = _re.search(r"\{.*\}", response, _re.DOTALL)
    if not m:
        raise HTTPException(status_code=502, detail="LLM returned no JSON")
    data = json.loads(m.group(0))

    # Sanitize fields
    fields = []
    for i, f in enumerate(data.get("fields") or []):
        ftype = f.get("type") or "text"
        if ftype not in {"text", "textarea", "date", "checkbox", "radio", "select", "signature", "email", "phone", "number"}:
            ftype = "text"
        fid = (f.get("id") or f.get("label") or f"field-{i+1}").lower()
        fid = "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in fid).strip("-") or f"field-{i+1}"
        fields.append({
            "id": fid,
            "type": ftype,
            "label": (f.get("label") or "").strip()[:200] or f"Field {i+1}",
            "required": bool(f.get("required")),
            "placeholder": (f.get("placeholder") or "")[:120] or None,
            "options": [str(o)[:80] for o in (f.get("options") or [])][:20],
            "help_text": (f.get("help_text") or "")[:300] or None,
        })

    cat = data.get("category") or hint_category or "other"
    if cat not in {"consent", "intake", "hipaa", "photo_release", "treatment", "other"}:
        cat = "other"

    return {
        "title": (data.get("title") or "Untitled form")[:120],
        "description": (data.get("description") or "")[:500],
        "category": cat,
        "fields": fields[:30],
    }


@api.get("/forms/templates", response_model=List[FormTemplateOut])
async def list_form_templates(
    include_inactive: bool = False,
    category: Optional[str] = None,
    user=Depends(get_current_user),
):
    if user["role"] == "client":
        raise HTTPException(status_code=403, detail="Forbidden")
    q: Dict[str, Any] = {}
    if not include_inactive:
        q["active"] = True
    if category:
        q["category"] = category
    rows = await db.form_templates.find(q).sort("created_at", -1).to_list(500)
    return [_strip_id(r) for r in rows]


@api.post("/forms/templates", response_model=FormTemplateOut)
async def create_form_template(payload: FormTemplateIn, request: Request,
                               user=Depends(require_roles("admin", "practitioner", "staff"))):
    now = datetime.now(timezone.utc)
    doc = payload.dict()
    doc["id"] = new_id()
    doc["builtin"] = False
    doc["created_by"] = user["id"]
    doc["created_by_name"] = user.get("full_name")
    doc["created_at"] = now
    doc["updated_at"] = now
    await db.form_templates.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "form_template.create",
                    resource_type="form_template", resource_id=doc["id"],
                    metadata={"title": doc.get("title")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/forms/templates/{tpl_id}", response_model=FormTemplateOut)
async def update_form_template(tpl_id: str, payload: FormTemplateIn, request: Request,
                               user=Depends(require_roles("admin", "practitioner", "staff"))):
    existing = await db.form_templates.find_one({"id": tpl_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    if existing.get("builtin") and user["role"] != "admin":
        # Allow admins to override built-ins; others may only clone
        raise HTTPException(status_code=403, detail="Built-in templates can only be edited by admins")
    updates = payload.dict()
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.form_templates.update_one({"id": tpl_id}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "form_template.update",
                    resource_type="form_template", resource_id=tpl_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    doc = await db.form_templates.find_one({"id": tpl_id})
    return _strip_id(doc)


@api.delete("/forms/templates/{tpl_id}")
async def delete_form_template(tpl_id: str, request: Request,
                               user=Depends(require_roles("admin"))):
    existing = await db.form_templates.find_one({"id": tpl_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    if existing.get("builtin"):
        # Soft-archive built-ins instead of deleting
        await db.form_templates.update_one({"id": tpl_id}, {"$set": {"active": False, "updated_at": datetime.now(timezone.utc)}})
    else:
        await db.form_templates.delete_one({"id": tpl_id})
    await log_audit(db, user["id"], user["email"], "form_template.delete",
                    resource_type="form_template", resource_id=tpl_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/forms/transcribe", response_model=FormTranscribeOut)
async def transcribe_form(file: UploadFile = File(...),
                          category: Optional[str] = Form(None),
                          user=Depends(require_roles("admin", "practitioner", "staff"))):
    """Upload a PDF/DOCX/TXT and AI-transcribe it into our form schema."""
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 8 MB)")
    text = _extract_text_from_upload(file.filename or "", data)
    if not text or len(text) < 30:
        raise HTTPException(status_code=400, detail="Document appears empty after extraction")
    result = await _llm_form_transcribe(text, hint_category=category)
    result["source"] = "ai"
    result["extracted_text_preview"] = text[:500]
    return result


@api.post("/forms/generate", response_model=FormTranscribeOut)
async def generate_form_from_prompt(payload: FormGenerateIn,
                                    user=Depends(require_roles("admin", "practitioner", "staff"))):
    """AI-generate a form from a free-text prompt (e.g., 'detox program consent for 6-week protocol')."""
    if not payload.prompt or len(payload.prompt) < 5:
        raise HTTPException(status_code=400, detail="Prompt is too short")
    seed = (
        f"Create a healthcare consent/intake form based on this request from clinic staff:\n\n"
        f"{payload.prompt}\n\n"
        f"Audience: wellness clinic patients. Tone: clear, plain language. "
        f"Include realistic fields appropriate to the request."
    )
    result = await _llm_form_transcribe(seed, hint_category=payload.category)
    result["source"] = "ai"
    result["extracted_text_preview"] = None
    return result


@api.post("/forms/send", response_model=FormSubmissionOut)
async def send_form(payload: FormSendIn, request: Request,
                    user=Depends(require_roles("admin", "practitioner", "staff"))):
    tpl = await db.form_templates.find_one({"id": payload.template_id})
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    client = None
    if payload.client_id:
        client = await db.clients.find_one({"id": payload.client_id})
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
    token = _secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=max(1, min(payload.expires_in_hours, 24 * 30)))
    doc = {
        "id": new_id(),
        "template_id": tpl["id"],
        "template_title": tpl.get("title"),
        "template_category": tpl.get("category"),
        "client_id": (client or {}).get("id"),
        "client_name": (client or {}).get("full_name") or (client or {}).get("email"),
        "appointment_id": payload.appointment_id,
        "sent_by_id": user["id"],
        "sent_by_name": user.get("full_name"),
        "answers": {},
        "signature_data": None,
        "status": "sent",
        "token": token,
        "expires_at": expires,
        "submitted_at": None,
        "created_at": now,
        "note": payload.note or None,
        "channel": payload.channel or "link",
        "delivery_target": payload.delivery_target or None,
        "delivery_status": "pending",
    }
    await db.form_submissions.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "form.send",
                    resource_type="form_submission", resource_id=doc["id"],
                    metadata={"template_id": tpl["id"], "client_id": (client or {}).get("id"), "channel": doc["channel"]},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    # Compose absolute submit URL using request origin
    base_url = os.environ.get("PUBLIC_BASE_URL", "") or str(request.base_url).rstrip("/").replace("/api", "")
    submit_url = f"{base_url}/forms/respond/{token}"

    delivery_status = "skipped"
    target = payload.delivery_target
    if (payload.channel or "link") == "email" and not target:
        target = (client or {}).get("email")
    if (payload.channel or "link") == "sms" and not target:
        target = (client or {}).get("phone")

    if payload.channel == "email" and target:
        await db.integration_log.insert_one({
            "id": new_id(), "service": "sendgrid", "action": "form.email",
            "payload": {"to": target, "subject": f"Please complete: {tpl.get('title','')}", "submission_id": doc["id"], "submit_url": submit_url},
            "_stubbed": True, "ts": now,
        })
        delivery_status = "sent_stub"
    elif payload.channel == "sms" and target:
        await db.integration_log.insert_one({
            "id": new_id(), "service": "twilio", "action": "form.sms",
            "payload": {"to": target, "body": f"{tpl.get('title','')} — please complete: {submit_url}", "submission_id": doc["id"]},
            "_stubbed": True, "ts": now,
        })
        delivery_status = "sent_stub"

    await db.form_submissions.update_one({"id": doc["id"]}, {"$set": {"delivery_status": delivery_status, "delivery_target": target}})
    doc["delivery_status"] = delivery_status
    doc["delivery_target"] = target

    out = _strip_id(doc)
    out["submit_url"] = submit_url
    # Best-effort push to client
    if client and client.get("user_id"):
        try:
            await push_to_user(
                client["user_id"],
                f"New form: {tpl.get('title','')}",
                "Tap to fill in and sign.",
                url=f"/forms/respond/{token}",
                tag=f"form-{doc['id']}",
            )
        except Exception:
            pass
    return out


@api.get("/forms/submissions", response_model=List[FormSubmissionOut])
async def list_form_submissions(
    status: Optional[str] = None,
    client_id: Optional[str] = None,
    template_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q: Dict[str, Any] = {"client_id": self_client["id"]}
    else:
        q = {}
    if status:
        q["status"] = status
    if client_id:
        q["client_id"] = client_id
    if template_id:
        q["template_id"] = template_id
    rows = await db.form_submissions.find(q).sort("created_at", -1).to_list(500)
    out = []
    for r in rows:
        d = _strip_id(r)
        if d.get("token"):
            d["submit_url"] = f"/forms/respond/{d['token']}"
        out.append(d)
    return out


# Public — no auth — for the responder
@api.get("/public/forms/{token}", response_model=FormPublicOut)
async def public_form_get(token: str):
    sub = await db.form_submissions.find_one({"token": token})
    if not sub:
        raise HTTPException(status_code=404, detail="Form link invalid or expired")
    if sub.get("status") == "void":
        raise HTTPException(status_code=410, detail="This form link has been voided")
    expires = sub.get("expires_at")
    if expires and isinstance(expires, datetime):
        cmp_exp = expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
        if cmp_exp < datetime.now(timezone.utc):
            await db.form_submissions.update_one({"id": sub["id"]}, {"$set": {"status": "expired"}})
            raise HTTPException(status_code=410, detail="This form link has expired")
    tpl = await db.form_templates.find_one({"id": sub["template_id"]})
    if not tpl:
        raise HTTPException(status_code=404, detail="Form template no longer exists")
    return {
        "template_id": tpl["id"],
        "title": tpl.get("title", ""),
        "description": tpl.get("description", ""),
        "category": tpl.get("category", "other"),
        "fields": tpl.get("fields", []),
        "client_name": sub.get("client_name"),
        "expires_at": sub.get("expires_at"),
        "already_submitted": sub.get("status") == "submitted",
    }


@api.post("/public/forms/{token}/submit", response_model=FormSubmissionOut)
async def public_form_submit(token: str, payload: FormSubmissionAnswers, request: Request):
    sub = await db.form_submissions.find_one({"token": token})
    if not sub:
        raise HTTPException(status_code=404, detail="Form link invalid")
    if sub.get("status") == "submitted":
        raise HTTPException(status_code=409, detail="Already submitted")
    if sub.get("status") in {"void", "expired"}:
        raise HTTPException(status_code=410, detail="This form is no longer accepting responses")
    expires = sub.get("expires_at")
    if expires and isinstance(expires, datetime):
        cmp = expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
        if cmp < datetime.now(timezone.utc):
            await db.form_submissions.update_one({"id": sub["id"]}, {"$set": {"status": "expired"}})
            raise HTTPException(status_code=410, detail="This form link has expired")

    now = datetime.now(timezone.utc)
    update = {
        "answers": payload.answers or {},
        "signature_data": payload.signature_data,
        "status": "submitted",
        "submitted_at": now,
    }
    await db.form_submissions.update_one({"id": sub["id"]}, {"$set": update})
    await log_audit(db, None, None, "form.submit_public",
                    resource_type="form_submission", resource_id=sub["id"],
                    metadata={"template_id": sub.get("template_id"), "client_id": sub.get("client_id")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    sub.update(update)
    out = _strip_id(sub)
    if out.get("token"):
        out["submit_url"] = f"/forms/respond/{out['token']}"
    return out


@api.get("/forms/submissions/{sub_id}", response_model=FormSubmissionOut)
async def get_form_submission(sub_id: str, user=Depends(require_roles("admin", "practitioner", "staff"))):
    sub = await db.form_submissions.find_one({"id": sub_id})
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    out = _strip_id(sub)
    if out.get("token"):
        out["submit_url"] = f"/forms/respond/{out['token']}"
    return out


# =================== PHASE 11: SOAP TEMPLATES ===================


@api.get("/soap-templates", response_model=List[SoapTemplateOut])
async def list_soap_templates(include_inactive: bool = False,
                              user=Depends(require_roles("admin", "practitioner", "staff"))):
    q: Dict[str, Any] = {}
    if not include_inactive:
        q["active"] = True
    rows = await db.soap_templates.find(q).sort("created_at", -1).to_list(200)
    return [_strip_id(r) for r in rows]


@api.post("/soap-templates", response_model=SoapTemplateOut)
async def create_soap_template(payload: SoapTemplateIn, request: Request,
                               user=Depends(require_roles("admin", "practitioner"))):
    now = datetime.now(timezone.utc)
    doc = payload.dict()
    doc["id"] = new_id()
    doc["created_by"] = user["id"]
    doc["created_by_name"] = user.get("full_name")
    doc["created_at"] = now
    doc["updated_at"] = now
    await db.soap_templates.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "soap_template.create",
                    resource_type="soap_template", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/soap-templates/{tpl_id}", response_model=SoapTemplateOut)
async def update_soap_template(tpl_id: str, payload: SoapTemplateIn, request: Request,
                               user=Depends(require_roles("admin", "practitioner"))):
    existing = await db.soap_templates.find_one({"id": tpl_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    updates = payload.dict()
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.soap_templates.update_one({"id": tpl_id}, {"$set": updates})
    doc = await db.soap_templates.find_one({"id": tpl_id})
    await log_audit(db, user["id"], user["email"], "soap_template.update",
                    resource_type="soap_template", resource_id=tpl_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.delete("/soap-templates/{tpl_id}")
async def delete_soap_template(tpl_id: str, request: Request,
                               user=Depends(require_roles("admin"))):
    await db.soap_templates.delete_one({"id": tpl_id})
    await log_audit(db, user["id"], user["email"], "soap_template.delete",
                    resource_type="soap_template", resource_id=tpl_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


# =================== PHASE 11: PROTOCOLS ===================


def _build_sessions_grid(weeks: int, sessions_per_week: int, label: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    for w in range(1, max(1, weeks) + 1):
        for s in range(1, max(1, sessions_per_week) + 1):
            out.append({
                "week": w,
                "session": s,
                "label": (label or "Session"),
                "completed": False,
                "completed_at": None,
                "completed_by_id": None,
                "completed_by_name": None,
                "notes": None,
            })
    return out


@api.get("/protocols/templates", response_model=List[ProtocolTemplateOut])
async def list_protocol_templates(include_inactive: bool = False,
                                  user=Depends(get_current_user)):
    if user["role"] == "client":
        # Clients only need to know names if proposed to them; they don't browse templates
        return []
    q: Dict[str, Any] = {}
    if not include_inactive:
        q["active"] = True
    rows = await db.protocol_templates.find(q).sort("created_at", -1).to_list(200)
    return [_strip_id(r) for r in rows]


@api.post("/protocols/templates", response_model=ProtocolTemplateOut)
async def create_protocol_template(payload: ProtocolTemplateIn, request: Request,
                                   user=Depends(require_roles("admin", "practitioner"))):
    now = datetime.now(timezone.utc)
    doc = payload.dict()
    doc["id"] = new_id()
    doc["builtin"] = False
    doc["created_by"] = user["id"]
    doc["created_by_name"] = user.get("full_name")
    doc["created_at"] = now
    doc["updated_at"] = now
    await db.protocol_templates.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "protocol_template.create",
                    resource_type="protocol_template", resource_id=doc["id"],
                    metadata={"title": doc.get("title")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/protocols/templates/{tpl_id}", response_model=ProtocolTemplateOut)
async def update_protocol_template(tpl_id: str, payload: ProtocolTemplateIn, request: Request,
                                   user=Depends(require_roles("admin", "practitioner"))):
    existing = await db.protocol_templates.find_one({"id": tpl_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    if existing.get("builtin") and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Built-in templates can only be edited by admins")
    updates = payload.dict()
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.protocol_templates.update_one({"id": tpl_id}, {"$set": updates})
    doc = await db.protocol_templates.find_one({"id": tpl_id})
    await log_audit(db, user["id"], user["email"], "protocol_template.update",
                    resource_type="protocol_template", resource_id=tpl_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.delete("/protocols/templates/{tpl_id}")
async def delete_protocol_template(tpl_id: str, request: Request,
                                   user=Depends(require_roles("admin"))):
    existing = await db.protocol_templates.find_one({"id": tpl_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    if existing.get("builtin"):
        await db.protocol_templates.update_one({"id": tpl_id}, {"$set": {"active": False, "updated_at": datetime.now(timezone.utc)}})
    else:
        await db.protocol_templates.delete_one({"id": tpl_id})
    await log_audit(db, user["id"], user["email"], "protocol_template.delete",
                    resource_type="protocol_template", resource_id=tpl_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


# ---- Protocol AI helpers ----


async def _llm_protocol_transcribe(source_text: str, hint_title: Optional[str] = None) -> dict:
    """Use Claude 4.5 to convert raw protocol text into our protocol template schema."""
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM key not configured")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"emergentintegrations unavailable: {e}")

    sys_msg = (
        "You convert wellness/detox/treatment protocol documents into a STRICT JSON object. "
        "Output JSON only — no commentary, no markdown.\n\n"
        "Schema:\n"
        "{\n"
        '  "title": "short title (max 80 chars)",\n'
        '  "description": "1–2 sentence summary",\n'
        '  "weeks": <int 1-52, default 4>,\n'
        '  "sessions_per_week": <int 1-14, default 1>,\n'
        '  "treatment_label": "Detox treatment | IV therapy | Massage | etc.",\n'
        '  "daily_outline": "markdown-formatted daily routine (breakfast/lunch/dinner if relevant)",\n'
        '  "foods_recommended": ["item1", "item2", ...],\n'
        '  "foods_avoid": ["item1", "item2", ...],\n'
        '  "lifestyle": "lifestyle bullets, newlines OK",\n'
        '  "supplements": [{"name": "...", "dose": "...", "frequency": "...", "notes": "..."}]\n'
        "}\n\n"
        "Rules: Detect duration explicitly stated in the document if any (e.g., '6-week detox' → weeks=6). "
        "Detect frequency (e.g., 'twice weekly treatments' → sessions_per_week=2). "
        "If the document only describes nutrition/lifestyle without explicit treatment cadence, default weeks=4, sessions_per_week=1. "
        "Pull bullet lists for foods_recommended and foods_avoid as JSON arrays of short strings. "
        "Keep daily_outline concise — under 1500 chars."
    )

    chat = LlmChat(
        api_key=api_key,
        session_id=f"protocol-transcribe-{new_id()[:8]}",
        system_message=sys_msg,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    response = await chat.send_message(UserMessage(text=f"Source:\n\n{source_text[:18000]}"))

    import re as _re
    m = _re.search(r"\{.*\}", response, _re.DOTALL)
    if not m:
        raise HTTPException(status_code=502, detail="LLM returned no JSON")
    data = json.loads(m.group(0))

    def _list(x): return [str(i)[:100] for i in (x or []) if str(i).strip()][:80]
    def _supps(x):
        out = []
        for s in (x or [])[:30]:
            if isinstance(s, dict):
                out.append({
                    "name": str(s.get("name", ""))[:120],
                    "dose": str(s.get("dose", ""))[:80],
                    "frequency": str(s.get("frequency", ""))[:80],
                    "notes": str(s.get("notes", ""))[:200],
                })
        return out

    weeks = int(data.get("weeks") or 4)
    spw = int(data.get("sessions_per_week") or 1)
    return {
        "title": (data.get("title") or hint_title or "Untitled protocol")[:120],
        "description": (data.get("description") or "")[:600],
        "weeks": max(1, min(52, weeks)),
        "sessions_per_week": max(1, min(14, spw)),
        "treatment_label": (data.get("treatment_label") or "Treatment session")[:80],
        "daily_outline": (data.get("daily_outline") or "")[:4000],
        "foods_recommended": _list(data.get("foods_recommended")),
        "foods_avoid": _list(data.get("foods_avoid")),
        "lifestyle": (data.get("lifestyle") or "")[:2000],
        "supplements": _supps(data.get("supplements")),
    }


@api.post("/protocols/transcribe")
async def transcribe_protocol(file: UploadFile = File(...),
                              user=Depends(require_roles("admin", "practitioner"))):
    """Upload a PDF/DOCX/TXT protocol document and AI-transcribe it into our schema."""
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 8 MB)")
    text = _extract_text_from_upload(file.filename or "", data)
    if not text or len(text) < 30:
        raise HTTPException(status_code=400, detail="Document appears empty after extraction")
    result = await _llm_protocol_transcribe(text, hint_title=(file.filename or "").rsplit(".", 1)[0])
    result["source"] = "ai"
    result["extracted_text_preview"] = text[:500]
    return result


@api.post("/protocols/generate")
async def generate_protocol(payload: FormGenerateIn,
                            user=Depends(require_roles("admin", "practitioner"))):
    """AI-generate a protocol from a free-text prompt (e.g., '6-week liver detox with weekly IV therapy')."""
    if not payload.prompt or len(payload.prompt) < 5:
        raise HTTPException(status_code=400, detail="Prompt is too short")
    seed = (
        f"Build a wellness/detox protocol based on this clinic-staff request:\n\n"
        f"{payload.prompt}\n\n"
        f"Use realistic naturopathic guidance. Choose a sensible weeks count + sessions per week."
    )
    result = await _llm_protocol_transcribe(seed)
    result["source"] = "ai"
    return result


# =================== UNIFIED DOCUMENT LIBRARY ===================


async def _llm_classify_document(text: str) -> dict:
    """Use Claude 4.5 to detect what kind of clinical document the staff just dropped in."""
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM key not configured")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"emergentintegrations unavailable: {e}")

    sys_msg = (
        "You are a clinical-document triage assistant for a wellness clinic. "
        "Given the contents of an uploaded document, classify it into ONE of these types:\n"
        "  • 'form'       — patient consent, HIPAA notice, photo release, intake questionnaire, anything the patient signs/fills.\n"
        "  • 'protocol'   — multi-week detox/cleanse/treatment plan with sessions, foods, lifestyle.\n"
        "  • 'soap'       — a SOAP note template with Subjective/Objective/Assessment/Plan sections.\n"
        "  • 'supplement' — supplement directions / dosing instructions sheet.\n"
        "  • 'other'      — anything else (lab result, marketing flyer, etc.).\n\n"
        "Output STRICT JSON only:\n"
        "{\n"
        '  "type": "form|protocol|soap|supplement|other",\n'
        '  "confidence": 0.0-1.0,\n'
        '  "title_guess": "short title",\n'
        '  "reasoning": "1-2 sentences explaining the classification",\n'
        '  "subcategory": "consent|intake|hipaa|photo_release|treatment|null"\n'
        "}\n"
        "No markdown. JSON only."
    )

    chat = LlmChat(
        api_key=api_key,
        session_id=f"doc-classify-{new_id()[:8]}",
        system_message=sys_msg,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    response = await chat.send_message(UserMessage(text=f"Document text:\n\n{text[:15000]}"))

    import re as _re
    m = _re.search(r"\{.*\}", response, _re.DOTALL)
    if not m:
        return {"type": "other", "confidence": 0.0, "title_guess": "Untitled", "reasoning": "LLM returned no JSON", "subcategory": None}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {"type": "other", "confidence": 0.0, "title_guess": "Untitled", "reasoning": "Failed to parse JSON", "subcategory": None}
    t = data.get("type") or "other"
    if t not in {"form", "protocol", "soap", "supplement", "other"}:
        t = "other"
    return {
        "type": t,
        "confidence": float(data.get("confidence") or 0.0),
        "title_guess": (data.get("title_guess") or "Untitled")[:120],
        "reasoning": (data.get("reasoning") or "")[:400],
        "subcategory": data.get("subcategory") or None,
    }


@api.post("/library/classify")
async def library_classify_document(file: UploadFile = File(...),
                                    user=Depends(require_roles("admin", "practitioner", "staff"))):
    """Universal ingest: classify a clinical document then run the right transcription path.
    Returns a `routed` payload with the destination type + a draft ready to pre-fill."""
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 8 MB)")
    text = _extract_text_from_upload(file.filename or "", data)
    if not text or len(text) < 30:
        raise HTTPException(status_code=400, detail="Document appears empty after extraction")
    classification = await _llm_classify_document(text)
    out = {
        "filename": file.filename,
        "size": len(data),
        "extracted_text_preview": text[:500],
        "classification": classification,
        "draft": None,
    }
    t = classification["type"]
    try:
        if t == "form":
            out["draft"] = await _llm_form_transcribe(text, hint_category=classification.get("subcategory"))
        elif t == "protocol":
            out["draft"] = await _llm_protocol_transcribe(text, hint_title=classification.get("title_guess"))
        elif t == "soap":
            out["draft"] = await _llm_soap_template_extract(text, hint_title=classification.get("title_guess"))
        elif t == "supplement":
            out["draft"] = await _llm_supplement_extract(text, hint_title=classification.get("title_guess"))
        else:
            out["draft"] = {"title": classification.get("title_guess") or "Untitled", "raw_text": text[:4000]}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Library transcription post-classify failed: %s", e)
        out["draft"] = {"title": classification.get("title_guess") or "Untitled", "raw_text": text[:4000], "error": str(e)}
    await log_audit(db, user["id"], user["email"], "library.classify",
                    resource_type="library", metadata={"type": t, "filename": file.filename})
    return out


async def _llm_soap_template_extract(text: str, hint_title: Optional[str] = None) -> dict:
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM key not configured")
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    sys_msg = (
        "Extract a SOAP note template from this document. Output STRICT JSON only:\n"
        "{ \"title\": \"...\", \"description\": \"...\", \"subjective\": \"...\", \"objective\": \"...\", \"assessment\": \"...\", \"plan\": \"...\", \"visit_type\": \"telehealth|in_person|null\" }"
    )
    chat = LlmChat(api_key=api_key, session_id=f"soap-extract-{new_id()[:8]}", system_message=sys_msg)\
        .with_model("anthropic", "claude-sonnet-4-5-20250929")
    response = await chat.send_message(UserMessage(text=f"Source:\n\n{text[:14000]}"))
    import re as _re
    m = _re.search(r"\{.*\}", response, _re.DOTALL)
    if not m:
        return {"title": hint_title or "SOAP template", "description": "", "subjective": "", "objective": "", "assessment": "", "plan": "", "visit_type": None}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"title": hint_title or "SOAP template", "description": text[:200], "subjective": text[:1000], "objective": "", "assessment": "", "plan": "", "visit_type": None}
    return {
        "title": (d.get("title") or hint_title or "SOAP template")[:120],
        "description": (d.get("description") or "")[:500],
        "subjective": (d.get("subjective") or "")[:4000],
        "objective": (d.get("objective") or "")[:4000],
        "assessment": (d.get("assessment") or "")[:4000],
        "plan": (d.get("plan") or "")[:4000],
        "visit_type": d.get("visit_type") if d.get("visit_type") in ("telehealth", "in_person") else None,
    }


async def _llm_supplement_extract(text: str, hint_title: Optional[str] = None) -> dict:
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM key not configured")
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    sys_msg = (
        "Extract a supplement directions sheet. Output STRICT JSON only:\n"
        "{ \"title\": \"...\", \"summary\": \"...\", \"items\": [{\"name\":\"...\",\"dose\":\"...\",\"frequency\":\"...\",\"timing\":\"...\",\"notes\":\"...\"}] }"
    )
    chat = LlmChat(api_key=api_key, session_id=f"supp-extract-{new_id()[:8]}", system_message=sys_msg)\
        .with_model("anthropic", "claude-sonnet-4-5-20250929")
    response = await chat.send_message(UserMessage(text=f"Source:\n\n{text[:14000]}"))
    import re as _re
    m = _re.search(r"\{.*\}", response, _re.DOTALL)
    if not m:
        return {"title": hint_title or "Supplement directions", "summary": "", "items": []}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"title": hint_title or "Supplement directions", "summary": text[:300], "items": []}
    items = []
    for it in (d.get("items") or [])[:50]:
        if not isinstance(it, dict):
            continue
        items.append({
            "name": str(it.get("name", ""))[:120],
            "dose": str(it.get("dose", ""))[:80],
            "frequency": str(it.get("frequency", ""))[:80],
            "timing": str(it.get("timing", ""))[:80],
            "notes": str(it.get("notes", ""))[:300],
        })
    return {
        "title": (d.get("title") or hint_title or "Supplement directions")[:120],
        "summary": (d.get("summary") or "")[:500],
        "items": items,
    }


# Persisted "Supplement directions" sheets — read-only lightweight CRUD
@api.post("/library/supplements")
async def save_supplement_sheet(payload: dict, request: Request,
                                user=Depends(require_roles("admin", "practitioner", "staff"))):
    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(),
        "title": str(payload.get("title", "Untitled"))[:120],
        "summary": str(payload.get("summary", ""))[:500],
        "items": payload.get("items") or [],
        "active": True,
        "created_by": user["id"],
        "created_by_name": user.get("full_name"),
        "created_at": now,
        "updated_at": now,
    }
    await db.supplement_sheets.insert_one(doc)
    return _strip_id(doc)


@api.get("/library/supplements")
async def list_supplement_sheets(user=Depends(require_roles("admin", "practitioner", "staff"))):
    rows = await db.supplement_sheets.find({"active": True}).sort("created_at", -1).to_list(200)
    return [_strip_id(r) for r in rows]


@api.delete("/library/supplements/{sheet_id}")
async def delete_supplement_sheet(sheet_id: str,
                                  user=Depends(require_roles("admin", "practitioner"))):
    await db.supplement_sheets.delete_one({"id": sheet_id})
    return {"ok": True}


@api.post("/protocols/enrollments", response_model=ProtocolEnrollmentOut)
async def create_protocol_enrollment(payload: ProtocolEnrollmentIn, request: Request,
                                     user=Depends(require_roles("admin", "practitioner"))):
    tpl = await db.protocol_templates.find_one({"id": payload.template_id})
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    client = await db.clients.find_one({"id": payload.client_id})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    weeks = payload.weeks or tpl.get("weeks") or 4
    spw = payload.sessions_per_week or tpl.get("sessions_per_week") or 1
    sessions = _build_sessions_grid(weeks, spw, tpl.get("treatment_label") or "Session")
    now = datetime.now(timezone.utc)
    snapshot = {k: tpl.get(k) for k in (
        "title", "description", "daily_outline", "foods_recommended", "foods_avoid",
        "supplements", "lifestyle", "treatment_label",
    )}
    doc = {
        "id": new_id(),
        "template_id": tpl["id"],
        "template_title": tpl.get("title"),
        "client_id": client["id"],
        "client_name": client.get("full_name") or client.get("email"),
        "practitioner_id": user["id"] if user["role"] == "practitioner" else None,
        "practitioner_name": user.get("full_name") if user["role"] == "practitioner" else None,
        "weeks": weeks,
        "sessions_per_week": spw,
        "status": "proposed",
        "sessions": sessions,
        "snapshot": snapshot,
        "custom_note": payload.custom_note,
        "proposed_at": now,
        "accepted_at": None,
        "completed_at": None,
        "created_by": user["id"],
        "created_by_name": user.get("full_name"),
    }
    await db.protocol_enrollments.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "protocol_enrollment.create",
                    resource_type="protocol_enrollment", resource_id=doc["id"],
                    metadata={"client_id": client["id"], "template_id": tpl["id"]},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    # Push to client portal user
    if client.get("user_id"):
        try:
            await push_to_user(
                client["user_id"],
                f"New protocol proposed: {tpl.get('title','')}",
                "Tap to review and accept your wellness protocol.",
                url="/portal/patient/protocols",
                tag=f"protocol-{doc['id']}",
            )
        except Exception:
            pass
    return _strip_id(doc)


@api.get("/protocols/enrollments", response_model=List[ProtocolEnrollmentOut])
async def list_protocol_enrollments(
    client_id: Optional[str] = None,
    practitioner_id: Optional[str] = None,
    status: Optional[str] = None,
    user=Depends(get_current_user),
):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q: Dict[str, Any] = {"client_id": self_client["id"]}
    else:
        q = {}
        if client_id:
            q["client_id"] = client_id
        if practitioner_id:
            q["practitioner_id"] = practitioner_id
    if status:
        q["status"] = status
    rows = await db.protocol_enrollments.find(q).sort("proposed_at", -1).to_list(500)
    return [_strip_id(r) for r in rows]


@api.get("/protocols/enrollments/{enr_id}", response_model=ProtocolEnrollmentOut)
async def get_protocol_enrollment(enr_id: str, user=Depends(get_current_user)):
    enr = await db.protocol_enrollments.find_one({"id": enr_id})
    if not enr:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or enr.get("client_id") != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    return _strip_id(enr)


@api.post("/protocols/enrollments/{enr_id}/decision", response_model=ProtocolEnrollmentOut)
async def decide_protocol(enr_id: str, payload: ProtocolDecisionIn, request: Request,
                          user=Depends(get_current_user)):
    enr = await db.protocol_enrollments.find_one({"id": enr_id})
    if not enr:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    # Either the client themselves, or staff/admin/practitioner can record decision
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or enr.get("client_id") != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    if enr["status"] != "proposed":
        raise HTTPException(status_code=409, detail=f"Cannot decide: current status is {enr['status']}")
    now = datetime.now(timezone.utc)
    if payload.decision == "accept":
        await db.protocol_enrollments.update_one(
            {"id": enr_id},
            {"$set": {"status": "active", "accepted_at": now}},
        )
    else:
        await db.protocol_enrollments.update_one(
            {"id": enr_id},
            {"$set": {"status": "declined", "completed_at": now, "custom_note": payload.note or enr.get("custom_note")}},
        )
    await log_audit(db, user["id"], user["email"], f"protocol.{payload.decision}",
                    resource_type="protocol_enrollment", resource_id=enr_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    enr = await db.protocol_enrollments.find_one({"id": enr_id})
    return _strip_id(enr)


@api.post("/protocols/enrollments/{enr_id}/sessions", response_model=ProtocolEnrollmentOut)
async def update_protocol_session(enr_id: str, payload: ProtocolSessionUpdate, request: Request,
                                  user=Depends(require_roles("admin", "practitioner", "staff"))):
    enr = await db.protocol_enrollments.find_one({"id": enr_id})
    if not enr:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if enr["status"] not in {"active", "accepted"}:
        raise HTTPException(status_code=409, detail=f"Protocol is {enr['status']}; cannot mark sessions")
    sessions = enr.get("sessions") or []
    matched = False
    for s in sessions:
        if s["week"] == payload.week and s["session"] == payload.session:
            matched = True
            if payload.completed is not None:
                s["completed"] = payload.completed
                if payload.completed:
                    s["completed_at"] = datetime.now(timezone.utc)
                    s["completed_by_id"] = user["id"]
                    s["completed_by_name"] = user.get("full_name")
                else:
                    s["completed_at"] = None
                    s["completed_by_id"] = None
                    s["completed_by_name"] = None
            if payload.notes is not None:
                s["notes"] = payload.notes
            break
    if not matched:
        raise HTTPException(status_code=404, detail="Session slot not found")
    update = {"sessions": sessions}
    # Auto-complete protocol when all sessions are done
    if all(s.get("completed") for s in sessions):
        update["status"] = "completed"
        update["completed_at"] = datetime.now(timezone.utc)
    await db.protocol_enrollments.update_one({"id": enr_id}, {"$set": update})
    await log_audit(db, user["id"], user["email"], "protocol.session_update",
                    resource_type="protocol_enrollment", resource_id=enr_id,
                    metadata={"week": payload.week, "session": payload.session, "completed": payload.completed},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    enr = await db.protocol_enrollments.find_one({"id": enr_id})
    return _strip_id(enr)


# =================== STARTUP ===================
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
    _client.close()


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
