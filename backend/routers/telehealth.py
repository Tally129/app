"""
Telehealth routes: room/token/consent/recording APIs plus the
self-hosted WebRTC signaling WebSocket, chat, GridFS recording upload/
download, and AI-assisted live-SOAP drafting endpoints.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from bson import ObjectId
from fastapi import (
    Depends, File, HTTPException, Query, Request, UploadFile,
    WebSocket, WebSocketDisconnect,
)

from audit import get_client_ip, log_audit
from deps import (
    _resolve_self_client, _strip_id, api, db, fs_bucket,
    get_current_user, logger, require_roles,
)
from models import TelehealthConsentIn, new_id
from auth_utils import decode_token


# ---------- Daily.co helpers (stubbed if DAILY_API_KEY unset) ----------
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


# ---------- Self-hosted WebRTC signaling ----------

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

