"""
Generic finalize + amend workflow for clinical documents.

All clinical documents (visit notes, treatment plans, form submissions,
consents, lab results, protocol assignments) share the same lifecycle:

    draft -> finalized  (immutable content, prior_versions snapshot)
    finalized + amendment (append-only addenda with reason + author + ts)

This module provides `finalize_document` and `amend_document` that operate on
any collection uniformly. Routers call these instead of hand-rolling the
snapshot/status transitions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from fastapi import HTTPException

from audit import log_audit


async def finalize_document(
    db, collection_name: str, doc_id: str, user: Dict[str, Any],
    *, immutable_fields: Iterable[str],
    audit_action: str, require_countersignature: bool = False,
    countersign_role_predicate=None, request=None,
    status_field: str = "status",
) -> Dict[str, Any]:
    """Finalize a clinical document. `status_field` may be overridden for
    collections that already use "status" for a domain state (e.g. plans use
    active/completed; forms use sent/submitted). In those cases the caller
    passes `status_field="lifecycle_status"` so the finalize state machine
    lives on a separate field."""
    coll = db[collection_name]
    doc = await coll.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"{collection_name} not found")
    if doc.get(status_field) == "finalized":
        return doc

    if require_countersignature and countersign_role_predicate and not countersign_role_predicate(user):
        raise HTTPException(status_code=403, detail={
            "code": "countersignature_required",
            "message": "Only a licensed practitioner or admin may finalize this record.",
        })

    now = datetime.now(timezone.utc)
    snapshot = {"version": 1, "author_id": doc.get("practitioner_id") or doc.get("author_id") or user["id"],
                "author_name": doc.get("practitioner_name") or doc.get("author_name") or user.get("full_name"),
                "finalized_at": now}
    for f in immutable_fields:
        snapshot[f] = doc.get(f)

    await coll.update_one(
        {"id": doc_id, status_field: {"$ne": "finalized"}},
        {"$set": {status_field: "finalized", "finalized_at": now,
                  "finalized_by": user["id"],
                  "finalized_by_name": user.get("full_name") or user.get("email"),
                  "updated_at": now},
         "$push": {"prior_versions": snapshot}},
    )
    await log_audit(
        db, user["id"], user["email"], audit_action,
        resource_type=collection_name, resource_id=doc_id,
        severity="high", outcome="success",
        metadata={"version": 1, "client_id": doc.get("client_id")},
        ip=(request.client.host if request and request.client else None) if request else None,
        user_agent=(request.headers.get("user-agent") if request else None),
    )
    return await coll.find_one({"id": doc_id})


async def amend_document(
    db, collection_name: str, doc_id: str, user: Dict[str, Any],
    *, content: str, reason: str,
    audit_action: str, request=None,
    status_field: str = "status",
) -> Dict[str, Any]:
    coll = db[collection_name]
    doc = await coll.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"{collection_name} not found")
    if doc.get(status_field) != "finalized" and doc.get(status_field) is not None:
        raise HTTPException(status_code=409, detail={
            "code": "not_finalized",
            "message": "Amendment requires a finalized record. Finalize the draft first.",
        })
    if not content or len(content.strip()) < 4:
        raise HTTPException(status_code=400, detail="Amendment content required")
    if not reason or len(reason.strip()) < 4:
        raise HTTPException(status_code=400, detail="Amendment reason required")

    addendum = {
        "author_id": user["id"],
        "author_name": user.get("full_name") or user.get("email"),
        "content": content,
        "reason": reason,
        "ts": datetime.now(timezone.utc),
    }
    await coll.update_one({"id": doc_id}, {"$push": {"amendments": addendum},
                                            "$set": {"updated_at": addendum["ts"]}})
    await log_audit(
        db, user["id"], user["email"], audit_action,
        resource_type=collection_name, resource_id=doc_id,
        severity="high", outcome="success",
        metadata={"client_id": doc.get("client_id"),
                  "reason_preview": reason[:80]},
        ip=(request.client.host if request and request.client else None) if request else None,
        user_agent=(request.headers.get("user-agent") if request else None),
    )
    return await coll.find_one({"id": doc_id})


def refuse_edit_if_finalized(doc: Dict[str, Any], status_field: str = "status"):
    if doc.get(status_field) == "finalized":
        raise HTTPException(status_code=409, detail={
            "code": "record_finalized",
            "message": "This record is finalized and cannot be edited. Use the amendment workflow.",
        })
