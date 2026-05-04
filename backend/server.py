from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from bson import ObjectId
import os
import io
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List

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
    new_id,
)
from datetime import timedelta
import httpx
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
    await log_audit(db, user["id"], user["email"], "note.create",
                    resource_type="note", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


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
    except Exception as e:
        logger.warning("Index creation warning: %s", e)

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
