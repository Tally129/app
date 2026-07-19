/**
 * Permission-scope helper for frontend components.
 *
 * Mirrors the backend ROLE_PERMISSIONS map so components can gate their
 * data fetches BEFORE issuing a request the current role would only be
 * denied for. This is the client-side echo of `permissions.py`.
 *
 * Contract:
 *   const { role } = useAuth().user || {};
 *   if (!can(role, "user:list")) return null;   // skip mount + fetch
 */
const ROLE_PERMISSIONS = {
  client: new Set([
    "client:read_self", "note:list_self",
    "file:upload_self", "file:download_self",
    "session:list_own", "session:revoke_own",
  ]),
  practitioner: new Set([
    "client:list", "client:read_assigned", "client:write",
    "note:list_assigned", "note:create", "note:amend", "note:finalize",
    "file:upload_any", "file:download_any",
    "session:list_own", "session:revoke_own",
    "appt:write",
  ]),
  staff: new Set([
    "client:list", "client:write",
    "file:upload_any",
    "session:list_own", "session:revoke_own",
    "appt:write", "inventory:write", "pos:write",
  ]),
  front_desk: new Set([
    "client:list", "client:write",
    "session:list_own", "session:revoke_own",
    "appt:write", "inventory:write", "pos:write",
  ]),
  admin: new Set([
    "user:list", "user:create", "user:update_role", "user:deactivate",
    "session:list_own", "session:list_any",
    "session:revoke_own", "session:revoke_any",
    "client:list", "client:read_any", "client:write",
    "note:list_any", "note:create", "note:amend", "note:finalize",
    "file:upload_any", "file:download_any", "file:delete_any",
    "audit:read", "breakglass:activate",
    "appt:write", "inventory:write", "pos:write",
  ]),
  auditor: new Set([
    "audit:read", "breakglass:read_all",
    "client:list", "client:read_any",
    "note:list_any",
    "file:download_any",
    "session:list_own", "session:revoke_own",
    "session:list_any",
  ]),
};

export function can(role, ...permissions) {
  if (!role) return false;
  const perms = ROLE_PERMISSIONS[role];
  if (!perms) return false;
  return permissions.some((p) => perms.has(p));
}
