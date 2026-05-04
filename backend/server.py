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
    new_id,
)
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
