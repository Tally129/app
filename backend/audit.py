from datetime import datetime, timezone
from typing import Optional, Dict, Any
import uuid


async def log_audit(
    db,
    user_id: Optional[str],
    user_email: Optional[str],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "ip": ip,
        "user_agent": user_agent,
        "metadata": metadata or {},
        "ts": datetime.now(timezone.utc),
    }
    try:
        await db.audit_logs.insert_one(doc)
    except Exception:
        pass
    return doc


def get_client_ip(request) -> Optional[str]:
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else None
    except Exception:
        return None
