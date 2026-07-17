"""
Clients + Intake + SOAP Notes + Files + Supplement assignments.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from audit import get_client_ip, log_audit
from notifiers import push_to_user
from deps import (
    _resolve_self_client, _strip_id, api, db, fs_bucket,
    get_current_user, require_roles,
)
from models import (
    AmendIn, ClientIn, ClientOut, FileMetaOut, IntakeIn, IntakeOut,
    NoteIn, NoteOut, new_id,
)


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
    doc["status"] = "draft"
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = doc["created_at"]
    doc["finalized_at"] = None
    doc["finalized_by"] = None
    doc["prior_versions"] = []
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


@api.put("/notes/{note_id}", response_model=NoteOut)
async def update_note(note_id: str, payload: NoteIn, request: Request,
                      user=Depends(require_roles("practitioner", "admin"))):
    """Draft-only edit. Once finalized, editing is refused (must amend instead)."""
    note = await db.visit_notes.find_one({"id": note_id})
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.get("status") == "finalized":
        raise HTTPException(status_code=409, detail={
            "code": "note_finalized",
            "message": "This note is finalized and cannot be edited. Use /amend to add an addendum.",
        })
    if note.get("practitioner_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only the author or an admin may edit a draft note")
    updates = payload.dict()
    updates.pop("client_id", None)  # locked to original
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.visit_notes.update_one({"id": note_id}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "note.update_draft",
                    resource_type="note", resource_id=note_id,
                    metadata={"fields": list(updates.keys())},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    note = await db.visit_notes.find_one({"id": note_id})
    return _strip_id(note)


@api.post("/notes/{note_id}/finalize", response_model=NoteOut)
async def finalize_note(note_id: str, request: Request,
                        user=Depends(require_roles("practitioner", "admin"))):
    """Transition a draft note to `finalized`. The finalized version is
    immutable — future changes must go through `/amend`."""
    note = await db.visit_notes.find_one({"id": note_id})
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.get("status") == "finalized":
        return _strip_id(note)
    if note.get("practitioner_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only the author or an admin may finalize")
    now = datetime.now(timezone.utc)
    # Snapshot the current content as the immutable version 1.
    snapshot = {
        "version": 1,
        "subjective": note.get("subjective"),
        "objective": note.get("objective"),
        "assessment": note.get("assessment"),
        "plan": note.get("plan"),
        "author_id": note.get("practitioner_id"),
        "author_name": note.get("practitioner_name"),
        "finalized_at": now,
    }
    await db.visit_notes.update_one(
        {"id": note_id, "status": {"$ne": "finalized"}},
        {"$set": {"status": "finalized", "finalized_at": now,
                  "finalized_by": user["id"], "updated_at": now},
         "$push": {"prior_versions": snapshot}},
    )
    await log_audit(db, user["id"], user["email"], "note.finalize",
                    resource_type="note", resource_id=note_id,
                    severity="high", outcome="success",
                    metadata={"client_id": note.get("client_id"), "version": 1},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    note = await db.visit_notes.find_one({"id": note_id})
    return _strip_id(note)


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
    # Amendment workflow only applies to finalized notes. Drafts should be edited via PUT.
    if note.get("status") != "finalized":
        # Backfill: legacy notes without a status are treated as finalized so the
        # amend endpoint remains callable on historical rows.
        if note.get("status") not in (None, "finalized"):
            raise HTTPException(status_code=409, detail={
                "code": "not_finalized",
                "message": "Amendment is only supported on finalized notes. Finalize first.",
            })
    reason = getattr(payload, "reason", None) or ""
    if not payload.content or len(payload.content.strip()) < 4:
        raise HTTPException(status_code=400, detail="Amendment content required")
    amendment = {
        "author_id": user["id"],
        "author_name": user.get("full_name", ""),
        "content": payload.content,
        "reason": reason,
        "ts": datetime.now(timezone.utc),
    }
    await db.visit_notes.update_one({"id": note_id}, {"$push": {"amendments": amendment}})
    await log_audit(db, user["id"], user["email"], "note.amend",
                    resource_type="note", resource_id=note_id,
                    severity="high", outcome="success",
                    metadata={"client_id": note.get("client_id"), "reason_preview": reason[:80]},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    note = await db.visit_notes.find_one({"id": note_id})
    return _strip_id(note)


# =================== FILES ===================
ALLOWED_CATEGORIES = {"lab", "intake", "image", "doc", "other"}
# Content-type allowlist. Enforced on upload; unknown MIME → 415.
ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.",  # docx/xlsx/pptx
    "application/msword", "application/vnd.ms-excel",
    "application/json", "text/plain", "text/csv",
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/heic", "image/heif",
    "audio/", "video/",  # for telehealth recordings
)
MAX_UPLOAD_BYTES = int(20 * 1024 * 1024)  # 20 MiB


def _safe_filename(name: str) -> str:
    """Strip path components + control chars; keep a POSIX-safe basename."""
    import re
    base = (name or "upload").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = re.sub(r"[\x00-\x1f]+", "", base).strip()
    base = re.sub(r"[^A-Za-z0-9._\-]+", "_", base)
    return base[:180] or "upload"


@api.post("/files/upload", response_model=FileMetaOut)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    client_id: Optional[str] = Form(None),
    category: str = Form("other"),
    user=Depends(get_current_user),
):
    import hashlib as _hashlib
    if category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Category must be one of {ALLOWED_CATEGORIES}")
    mime = (file.content_type or "").lower()
    if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {mime or 'unknown'}")

    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = self_client["id"]
    else:
        # Workforce upload must specify a client the actor can see.
        if client_id:
            target = await db.clients.find_one({"id": client_id})
            if not target:
                raise HTTPException(status_code=404, detail="Client not found")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (20 MiB max)")

    checksum = _hashlib.sha256(content).hexdigest()
    safe_name = _safe_filename(file.filename)
    gridfs_id = await fs_bucket.upload_from_stream(safe_name, io.BytesIO(content),
                                                   metadata={"mime": mime, "sha256": checksum})
    meta = {
        "id": new_id(),
        "gridfs_id": str(gridfs_id),
        "filename": safe_name,
        "mime": mime or "application/octet-stream",
        "size": len(content),
        "sha256": checksum,
        "category": category,
        "client_id": client_id,
        "uploaded_by": user["id"],
        "uploaded_by_name": user.get("full_name", ""),
        "created_at": datetime.now(timezone.utc),
        "deleted_at": None,
        # Malware-scan integration point — provider plugs in and updates this.
        "scan_status": "pending",
        "scan_provider": None,
        "scan_result": None,
    }
    await db.files.insert_one(meta)
    await log_audit(db, user["id"], user["email"], "file.upload",
                    resource_type="file", resource_id=meta["id"],
                    metadata={"client_id": client_id, "category": category,
                              "size": len(content), "sha256": checksum, "mime": mime},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(meta)


@api.get("/files", response_model=List[FileMetaOut])
async def list_files(client_id: Optional[str] = None, user=Depends(get_current_user)):
    q: Dict[str, Any] = {"deleted_at": None}
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
    if meta.get("deleted_at"):
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
                    metadata={"client_id": meta.get("client_id"), "sha256": meta.get("sha256"),
                              "size": meta.get("size")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    fname = _safe_filename(meta["filename"])
    return StreamingResponse(
        io.BytesIO(data),
        media_type=meta.get("mime", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request,
                      user=Depends(require_roles("admin", "practitioner"))):
    """Soft-delete: mark `deleted_at` + record who + high-severity audit. The
    GridFS blob is NOT purged (retention-ready)."""
    meta = await db.files.find_one({"id": file_id})
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    if meta.get("deleted_at"):
        return {"ok": True, "already_deleted": True}
    await db.files.update_one({"id": file_id}, {"$set": {
        "deleted_at": datetime.now(timezone.utc),
        "deleted_by": user["id"],
        "deleted_by_name": user.get("full_name") or user.get("email"),
    }})
    await log_audit(db, user["id"], user["email"], "file.delete",
                    resource_type="file", resource_id=file_id,
                    severity="high", outcome="success",
                    metadata={"client_id": meta.get("client_id"), "sha256": meta.get("sha256")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


