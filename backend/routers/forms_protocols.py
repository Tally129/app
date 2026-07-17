"""
Forms & consents + SOAP templates + Protocols + Library classification.

Extracted from server.py during Phase 16 refactor.
All handlers register on the shared `deps.api` APIRouter.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile

from audit import get_client_ip, log_audit
from deps import (
    _resolve_self_client, _strip_id, api, db, get_current_user,
    logger, require_roles,
)
from models import (
    FormGenerateIn, FormPublicOut, FormSendIn, FormSubmissionAnswers,
    FormSubmissionOut, FormTemplateIn, FormTemplateOut, FormTranscribeOut,
    ProtocolDecisionIn, ProtocolEnrollmentIn, ProtocolEnrollmentOut,
    ProtocolSessionUpdate, ProtocolTemplateIn, ProtocolTemplateOut,
    SoapTemplateIn, SoapTemplateOut, new_id,
)


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
