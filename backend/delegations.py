"""
Provider-authorized delegated editing for clinical documentation.

A provider may grant a Medical Assistant or Admin the ability to draft or
edit unsigned clinical documents on their behalf, either blanket (all
patients assigned to the provider) or scoped to a specific client. Only
providers may finalize / amend / sign / prescribe / lock — that stays hard-
coded at the route level.

Data model  (`db.clinical_delegations`):
    id, provider_id, provider_name,
    delegate_id, delegate_name, delegate_role,
    client_id: Optional[str]     # None = all of provider's patients
    scope: "documentation"       # forward-compatible (future scopes)
    created_at, expires_at, revoked_at
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from deps import db


ELIGIBLE_DELEGATE_ROLES = {"medical_assistant", "admin"}
DEFAULT_TTL = timedelta(hours=24)
MAX_TTL = timedelta(days=7)


async def has_active_delegation(
    user: dict,
    client_id: Optional[str],
    provider_id: Optional[str] = None,
) -> Optional[dict]:
    """Return the active delegation doc if user is delegated to draft on
    behalf of a provider for `client_id`. Providers never need delegation
    for their own records; this helper returns None for provider callers.
    """
    role = user.get("role")
    if role not in ELIGIBLE_DELEGATE_ROLES:
        return None
    now = datetime.now(timezone.utc)
    query: dict = {
        "delegate_id": user["id"],
        "expires_at": {"$gt": now},
        "revoked_at": None,
    }
    if provider_id:
        query["provider_id"] = provider_id
    # Match blanket delegation (client_id is None) OR client-scoped.
    if client_id:
        query["$or"] = [{"client_id": client_id}, {"client_id": None}]
    else:
        query["client_id"] = None
    return await db.clinical_delegations.find_one(query)


def compute_edit_state(user: dict, record_status: Optional[str], delegation: Optional[dict]) -> str:
    """UI-facing state string.

    - `finalized` — record is locked; only amend (provider) allowed
    - `draft_editing` — user is authorized to edit the draft
    - `awaiting_review` — the record is a draft but user cannot edit (no auth)
    - `read_only` — user has no edit path
    """
    status = (record_status or "draft").lower()
    role = user.get("role")
    if status == "finalized":
        return "finalized"
    if role == "practitioner":
        return "draft_editing"
    if role in ELIGIBLE_DELEGATE_ROLES and delegation:
        return "draft_editing"
    if role in ELIGIBLE_DELEGATE_ROLES:
        return "read_only"
    return "read_only"
