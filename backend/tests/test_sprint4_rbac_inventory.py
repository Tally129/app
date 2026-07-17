"""
Route inventory + RBAC coverage test.

Fails when:
  * a protected route has NO auth dependency (i.e. it is anonymous by accident)
  * a role-based dep resolves to an EMPTY permission set (misconfigured catalog)

Public endpoints must be declared in `PUBLIC_ROUTES` (path + method) so the
allow-list is explicit — adding a new anonymous endpoint requires an explicit
allow-list edit and code review.
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")

from server import app  # noqa: E402
from permissions import ROLE_PERMISSIONS, permissions_for_roles  # noqa: E402


# Deliberate anonymous endpoints — public API surface.
PUBLIC_ROUTES = {
    ("GET",  "/api/health"),
    ("GET",  "/api/"),
    ("GET",  "/api/push/public-key"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/login/continue"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/forgot-password"),
    ("POST", "/api/auth/reset-password"),
    ("GET",  "/api/auth/google/oauth/authorize"),
    ("GET",  "/api/auth/google/oauth/callback"),
    ("POST", "/api/auth/google/oauth/exchange"),
    ("POST", "/api/auth/google/session"),
    ("POST", "/api/auth/dev/reset-token"),
    ("GET",  "/api/forms/public/{token}"),
    ("POST", "/api/forms/public/{token}"),
    ("GET",  "/api/public/forms/{token}"),
    ("POST", "/api/public/forms/{token}/submit"),
    ("POST", "/api/public/appointment-request"),
    ("POST", "/api/public/vip-signup"),
    ("POST", "/api/webhooks/twilio/sms"),
    ("POST", "/api/webhooks/sendgrid"),
    ("GET",  "/api/csp-report"),
    ("POST", "/api/csp-report"),
    # WebSocket handshakes carry their own auth ticket (`?ticket=...`)
}

# Endpoints that must be reachable to complete auth (their callers have a
# session but not necessarily a role gate yet).
NEUTRAL_AUTH_ROUTES = {
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/logout-all"),
    ("GET",  "/api/auth/sessions"),
    ("DELETE", "/api/auth/sessions/{session_id}"),
    ("POST", "/api/auth/mfa/setup"),
    ("POST", "/api/auth/mfa/enable"),
    ("POST", "/api/auth/mfa/disable"),
    ("POST", "/api/auth/mfa/verify"),
    ("POST", "/api/auth/change-password"),
    ("GET",  "/api/auth/me"),
    ("GET",  "/api/breakglass/active"),
    ("POST", "/api/breakglass/{bg_id}/revoke"),
}


def _dep_names(route):
    """Return the string names of every dependency callable on the route."""
    names = []
    dependant = getattr(route, "dependant", None)
    if not dependant:
        return names
    def walk(d):
        for sub in d.dependencies:
            call = getattr(sub, "call", None)
            if call:
                names.append(getattr(call, "__name__", str(call)))
            walk(sub)
    walk(dependant)
    endpoint = getattr(route, "endpoint", None)
    if endpoint:
        sig = inspect.signature(endpoint)
        for p in sig.parameters.values():
            if p.default is not inspect._empty:
                dep = getattr(p.default, "dependency", None)
                if dep:
                    names.append(getattr(dep, "__name__", str(dep)))
    return names


def _iter_api_routes():
    from starlette.routing import Route
    for r in app.routes:
        if not isinstance(r, Route):
            continue
        if not r.path.startswith("/api"):
            continue
        methods = r.methods or set()
        for m in methods:
            if m == "HEAD":
                continue
            yield m, r.path, r


def test_every_protected_route_has_auth_dependency():
    """Every /api route not in PUBLIC_ROUTES must sit behind an auth dep."""
    protected_deps = {
        "get_current_user", "get_authenticated_user",
        "require_roles", "require_permission",
        "require_workforce_mfa", "dep",
    }
    unprotected = []
    for method, path, route in _iter_api_routes():
        key = (method, path)
        if key in PUBLIC_ROUTES or key in NEUTRAL_AUTH_ROUTES:
            continue
        deps = _dep_names(route)
        if not any(d in protected_deps or d.startswith(("get_current", "require_")) for d in deps):
            unprotected.append((method, path, deps))
    assert not unprotected, (
        "Found protected /api routes with no auth dependency:\n"
        + "\n".join(f"  {m} {p}  deps={d}" for m, p, d in unprotected)
    )


def test_role_map_never_grants_empty_permission_set():
    """Every role listed in ROLE_PERMISSIONS must resolve to at least one perm.
    Empty grants are a config bug that would let requests through role-only
    checks with no catalog permission."""
    for role, perms in ROLE_PERMISSIONS.items():
        assert perms, f"Role '{role}' has no permissions in the catalog"


def test_role_combinations_used_by_require_roles_have_nonempty_union():
    """Verify each combination `require_roles(*roles)` used in the codebase
    resolves to a non-empty permission union."""
    combos = [
        ("admin",),
        ("admin", "practitioner"),
        ("admin", "practitioner", "staff"),
        ("admin", "staff"),
        ("admin", "staff", "practitioner"),
        ("practitioner", "admin"),
        ("practitioner", "admin", "staff"),
    ]
    for combo in combos:
        assert permissions_for_roles(*combo), \
            f"require_roles{combo} resolves to an empty permission set"


def test_admin_clinical_permissions_are_explicit_not_wildcard():
    """Admin's clinical permissions must be listed, not implied by role name."""
    admin_perms = ROLE_PERMISSIONS["admin"]
    for required in ("note:create", "note:amend", "note:finalize",
                     "client:read_any", "file:download_any", "audit:read"):
        assert required in admin_perms, f"admin must explicitly hold {required}"


def test_auditor_is_read_only():
    """Auditor must never carry write permissions."""
    write_permissions = {"client:write", "note:create", "note:amend",
                         "file:upload_any", "file:delete_any", "appt:write",
                         "pos:write", "inventory:write", "user:create",
                         "user:update_role", "user:deactivate",
                         "breakglass:activate", "session:revoke_any"}
    auditor_perms = ROLE_PERMISSIONS["auditor"]
    leaks = auditor_perms & write_permissions
    assert not leaks, f"auditor has write leak: {leaks}"


def test_client_is_self_scoped_only():
    """Client role must never have any *_any permission."""
    client_perms = ROLE_PERMISSIONS["client"]
    wildcard_leaks = {p for p in client_perms if p.endswith("_any")}
    assert not wildcard_leaks, f"client leaked wildcard perm(s): {wildcard_leaks}"
