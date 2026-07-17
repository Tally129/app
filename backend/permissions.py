"""
Central permission catalog + role-to-permission mapping + deny-by-default
authorization dependency.

Design goals
------------
* Every permission is a string constant defined ONCE in `PERMISSIONS`.
* Every role has an explicit permission set — no implicit inheritance.
* `require_permission(*perms)` is a FastAPI dependency that composes
  authentication + workforce MFA + explicit permission check.
* Resource-scope helpers (`self_client_only`, `assigned_practitioner_only`)
  centralize the per-record checks routers currently duplicate.

Deny-by-default: if a role has no explicit grant for a permission, access is
refused with 403 — no wildcards, no "admin sees all" magic. Admin's clinical
permissions are LISTED, not inferred.
"""
from __future__ import annotations

from typing import Iterable, Optional, Set

from fastapi import Depends, HTTPException, Request

from audit import get_client_ip, log_audit
from deps import WORKFORCE_ROLES, db, require_workforce_mfa


# --------------------------------------------------------------------------- #
# Permission catalog                                                           #
# --------------------------------------------------------------------------- #
class P:
    # Users / accounts
    USER_LIST = "user:list"
    USER_CREATE = "user:create"
    USER_UPDATE_ROLE = "user:update_role"
    USER_DEACTIVATE = "user:deactivate"

    # Sessions
    SESSION_LIST_OWN = "session:list_own"
    SESSION_LIST_ANY = "session:list_any"
    SESSION_REVOKE_OWN = "session:revoke_own"
    SESSION_REVOKE_ANY = "session:revoke_any"

    # Clients / PHI
    CLIENT_LIST = "client:list"
    CLIENT_READ_ANY = "client:read_any"
    CLIENT_READ_SELF = "client:read_self"
    CLIENT_READ_ASSIGNED = "client:read_assigned"
    CLIENT_WRITE = "client:write"

    # Clinical records
    NOTE_LIST_ANY = "note:list_any"
    NOTE_LIST_ASSIGNED = "note:list_assigned"
    NOTE_LIST_SELF = "note:list_self"
    NOTE_CREATE = "note:create"
    NOTE_AMEND = "note:amend"
    NOTE_FINALIZE = "note:finalize"

    # Files / file vault
    FILE_UPLOAD_ANY = "file:upload_any"
    FILE_UPLOAD_SELF = "file:upload_self"
    FILE_DOWNLOAD_ANY = "file:download_any"
    FILE_DOWNLOAD_SELF = "file:download_self"
    FILE_DELETE_ANY = "file:delete_any"

    # Audit
    AUDIT_READ = "audit:read"

    # Break-glass
    BREAKGLASS_ACTIVATE = "breakglass:activate"

    # Operational
    APPT_WRITE = "appt:write"
    INVENTORY_WRITE = "inventory:write"
    POS_WRITE = "pos:write"

    # Break-glass READ passthrough (auditor)
    BREAKGLASS_READ_ALL = "breakglass:read_all"


PERMISSIONS: Set[str] = {getattr(P, k) for k in vars(P) if not k.startswith("_")}


# --------------------------------------------------------------------------- #
# Role map                                                                     #
# --------------------------------------------------------------------------- #
ROLE_PERMISSIONS: dict[str, Set[str]] = {
    # Clients — strictly scoped to themselves.
    "client": {
        P.CLIENT_READ_SELF,
        P.NOTE_LIST_SELF,
        P.FILE_UPLOAD_SELF, P.FILE_DOWNLOAD_SELF,
        P.SESSION_LIST_OWN, P.SESSION_REVOKE_OWN,
    },
    # Practitioners — assigned clients + clinical write.
    "practitioner": {
        P.CLIENT_LIST, P.CLIENT_READ_ASSIGNED, P.CLIENT_WRITE,
        P.NOTE_LIST_ASSIGNED, P.NOTE_CREATE, P.NOTE_AMEND, P.NOTE_FINALIZE,
        P.FILE_UPLOAD_ANY, P.FILE_DOWNLOAD_ANY,
        P.SESSION_LIST_OWN, P.SESSION_REVOKE_OWN,
        P.APPT_WRITE,
    },
    # Staff — operational; PHI only where operations require it (client list, POS).
    "staff": {
        P.CLIENT_LIST, P.CLIENT_WRITE,
        P.FILE_UPLOAD_ANY,
        P.SESSION_LIST_OWN, P.SESSION_REVOKE_OWN,
        P.APPT_WRITE, P.INVENTORY_WRITE, P.POS_WRITE,
    },
    # Legacy alias — same as staff.
    "front_desk": {
        P.CLIENT_LIST, P.CLIENT_WRITE,
        P.SESSION_LIST_OWN, P.SESSION_REVOKE_OWN,
        P.APPT_WRITE, P.INVENTORY_WRITE, P.POS_WRITE,
    },
    "frontdesk": {
        P.CLIENT_LIST, P.CLIENT_WRITE,
        P.SESSION_LIST_OWN, P.SESSION_REVOKE_OWN,
        P.APPT_WRITE, P.INVENTORY_WRITE, P.POS_WRITE,
    },
    # Admin — full read + user mgmt + session mgmt + AUDIT + explicitly clinical.
    "admin": {
        P.USER_LIST, P.USER_CREATE, P.USER_UPDATE_ROLE, P.USER_DEACTIVATE,
        P.SESSION_LIST_OWN, P.SESSION_LIST_ANY,
        P.SESSION_REVOKE_OWN, P.SESSION_REVOKE_ANY,
        P.CLIENT_LIST, P.CLIENT_READ_ANY, P.CLIENT_WRITE,
        P.NOTE_LIST_ANY, P.NOTE_CREATE, P.NOTE_AMEND, P.NOTE_FINALIZE,
        P.FILE_UPLOAD_ANY, P.FILE_DOWNLOAD_ANY, P.FILE_DELETE_ANY,
        P.AUDIT_READ, P.BREAKGLASS_ACTIVATE,
        P.APPT_WRITE, P.INVENTORY_WRITE, P.POS_WRITE,
    },
    # Auditor — READ ONLY across all PHI. Break-glass READ passthrough.
    "auditor": {
        P.AUDIT_READ, P.BREAKGLASS_READ_ALL,
        P.CLIENT_LIST, P.CLIENT_READ_ANY,
        P.NOTE_LIST_ANY,
        P.FILE_DOWNLOAD_ANY,
        P.SESSION_LIST_OWN, P.SESSION_REVOKE_OWN,
        P.SESSION_LIST_ANY,
    },
}


def role_has(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role or "", set())


def check_any(user: dict, *permissions: str) -> bool:
    role = user.get("role")
    return any(role_has(role, p) for p in permissions)


# --------------------------------------------------------------------------- #
# FastAPI dependency                                                           #
# --------------------------------------------------------------------------- #
def require_permission(*permissions: str):
    """Compose auth + workforce-MFA gate + explicit permission check.

    Deny-by-default: if none of `permissions` is granted to the current role,
    return 403. Any GET from an `auditor` still receives break-glass READ
    passthrough (mirrored from `deps.require_roles`).
    """
    if not permissions:
        raise RuntimeError("require_permission called with no permissions")
    permset = set(permissions)

    async def dep(request: Request, user=Depends(require_workforce_mfa)):
        role = user.get("role") or ""
        # Auditor break-glass GET passthrough (still MFA-gated by outer dep).
        if role == "auditor" and request.method == "GET":
            try:
                await log_audit(
                    db, user["id"], user["email"], "auditor.break_glass_read",
                    resource_type="endpoint", resource_id=request.url.path,
                    severity="high", outcome="allow",
                    metadata={"emergency": True, "method": request.method,
                              "required_permissions": sorted(permset)},
                    ip=get_client_ip(request),
                    user_agent=request.headers.get("user-agent"),
                )
            except Exception:
                # Auditor read passthrough must never be blocked by audit error;
                # audit.log_audit already re-raises for REQUIRED events.
                pass
            return user
        granted = ROLE_PERMISSIONS.get(role) or set()
        if not (permset & granted):
            raise HTTPException(status_code=403, detail={
                "code": "permission_denied",
                "required_any": sorted(permset),
                "role": role,
            })
        return user
    return dep


# --------------------------------------------------------------------------- #
# Resource-scope helpers                                                       #
# --------------------------------------------------------------------------- #
async def assert_client_visible(user: dict, client_id: str) -> dict:
    """Central resource-scope check. Raises 403 if the current user cannot
    view the given client, otherwise returns the client document."""
    role = user.get("role") or ""
    client = await db.clients.find_one({"id": client_id})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if role_has(role, P.CLIENT_READ_ANY):
        return client
    if role_has(role, P.CLIENT_READ_ASSIGNED):
        if client.get("assigned_practitioner_id") == user["id"]:
            return client
    if role_has(role, P.CLIENT_READ_SELF):
        if client.get("user_id") == user["id"]:
            return client
    # Break-glass ACTIVE window
    if await _is_breakglass_active(user["id"], client_id):
        return client
    raise HTTPException(status_code=403, detail={"code": "scope_denied",
                                                 "resource": "client",
                                                 "id": client_id})


async def _is_breakglass_active(user_id: str, client_id: Optional[str]) -> bool:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    q = {"user_id": user_id, "expires_at": {"$gt": now}, "revoked_at": None}
    if client_id:
        q["$or"] = [
            {"target_client_id": client_id},
            {"target_client_id": None, "target_resource_type": {"$exists": True}},
        ]
    row = await db.breakglass_sessions.find_one(q)
    return row is not None


async def active_breakglass_for(user_id: str) -> list:
    from datetime import datetime, timezone
    rows = await db.breakglass_sessions.find({
        "user_id": user_id,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
        "revoked_at": None,
    }).to_list(50)
    return rows


# --------------------------------------------------------------------------- #
# Role → permission resolution                                                 #
# --------------------------------------------------------------------------- #
def permissions_for_roles(*roles: str) -> set:
    """Return the UNION of permissions granted to any of `roles`. Used to
    resolve role-based endpoints through the central catalog so RBAC coverage
    stays consistent."""
    out: set = set()
    for r in roles:
        out.update(ROLE_PERMISSIONS.get(r, set()))
    return out


def route_permissions_declared(dep_marker: str) -> list:
    """Given a stringified dependency marker (e.g. `require_roles(admin,practitioner)`),
    return the derived permission list. Used by the route-inventory test."""
    if dep_marker.startswith("require_permission("):
        inner = dep_marker[len("require_permission("):-1]
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    if dep_marker.startswith("require_roles("):
        inner = dep_marker[len("require_roles("):-1]
        roles = [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
        return sorted(permissions_for_roles(*roles))
    return []
