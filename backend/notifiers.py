"""
Email + SMS delivery with real-SDK-or-stub fallback.

Behavior:
- `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` set  → send real email via SendGrid
- Missing either                                   → write `_stubbed: True` doc to
                                                     `integration_log` and return
                                                     status `"sent_stub"`

- `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` + `TWILIO_FROM_NUMBER` set → real SMS
- Missing any                                                            → sent_stub

Every call also writes to `integration_log` so admins can audit outbound messages.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nms.notify")


def email_status() -> str:
    """Return "live" or "sent_stub" — for /api/health + admin dashboards."""
    if os.environ.get("SENDGRID_API_KEY") and os.environ.get("SENDGRID_FROM_EMAIL"):
        return "live"
    return "sent_stub"


def sms_status() -> str:
    if (
        os.environ.get("TWILIO_ACCOUNT_SID")
        and os.environ.get("TWILIO_AUTH_TOKEN")
        and os.environ.get("TWILIO_FROM_NUMBER")
    ):
        return "live"
    return "sent_stub"


# --------------------------------------------------------------------------- #
# Email                                                                        #
# --------------------------------------------------------------------------- #
async def send_email(
    db,
    to: str,
    subject: str,
    html: str,
    *,
    plain_text: Optional[str] = None,
    action: str = "email.generic",
    payload_metadata: Optional[dict] = None,
) -> str:
    """Send transactional email. Returns 'sent' | 'sent_stub' | 'failed'."""
    now = datetime.now(timezone.utc)
    log_doc = {
        "service": "sendgrid",
        "action": action,
        "payload": {"to": to, "subject": subject, **(payload_metadata or {})},
        "ts": now,
    }
    if email_status() != "live":
        log_doc["_stubbed"] = True
        await db.integration_log.insert_one(log_doc)
        return "sent_stub"

    api_key = os.environ["SENDGRID_API_KEY"]
    from_email = os.environ["SENDGRID_FROM_EMAIL"]

    def _blocking_send() -> int:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        msg = Mail(
            from_email=from_email, to_emails=to, subject=subject,
            html_content=html, plain_text_content=plain_text or "",
        )
        sg = SendGridAPIClient(api_key)
        r = sg.send(msg)
        return r.status_code

    try:
        code = await asyncio.to_thread(_blocking_send)
        log_doc.update({"status_code": code, "_stubbed": False})
        await db.integration_log.insert_one(log_doc)
        return "sent" if 200 <= code < 300 else "failed"
    except Exception as e:
        log_doc.update({"error": str(e), "_stubbed": False, "failed": True})
        await db.integration_log.insert_one(log_doc)
        logger.warning("SendGrid send failed: %s", e)
        return "failed"


# --------------------------------------------------------------------------- #
# SMS                                                                          #
# --------------------------------------------------------------------------- #
async def send_sms(
    db,
    to: str,
    body: str,
    *,
    action: str = "sms.generic",
    payload_metadata: Optional[dict] = None,
) -> str:
    """Send transactional SMS. Returns 'sent' | 'sent_stub' | 'failed'."""
    now = datetime.now(timezone.utc)
    log_doc = {
        "service": "twilio",
        "action": action,
        "payload": {"to": to, "body": body, **(payload_metadata or {})},
        "ts": now,
    }
    if sms_status() != "live":
        log_doc["_stubbed"] = True
        await db.integration_log.insert_one(log_doc)
        return "sent_stub"

    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    from_ = os.environ["TWILIO_FROM_NUMBER"]

    def _blocking_send() -> str:
        from twilio.rest import Client
        c = Client(sid, token)
        m = c.messages.create(to=to, from_=from_, body=body)
        return m.sid

    try:
        message_sid = await asyncio.to_thread(_blocking_send)
        log_doc.update({"twilio_sid": message_sid, "_stubbed": False})
        await db.integration_log.insert_one(log_doc)
        return "sent"
    except Exception as e:
        log_doc.update({"error": str(e), "_stubbed": False, "failed": True})
        await db.integration_log.insert_one(log_doc)
        logger.warning("Twilio send failed: %s", e)
        return "failed"
