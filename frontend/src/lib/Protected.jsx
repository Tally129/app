import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth, isWorkforceRole } from "./auth";

/**
 * Route guard.
 *
 * Redirect rules for signed-out visitors:
 *   • routes that ONLY admit `client` (e.g. `/portal/patient/*`) → `/login`
 *   • every other portal route (staff / provider / admin / MA / auditor)
 *     → `/staff-login`
 *   The originally-requested path is stashed in `location.state.from` so
 *   both login pages can bounce the user back after auth.
 *
 * Signed-in users who lack the required role fall through to their
 * role-appropriate portal home via `<Navigate to="/portal">` (which passes
 * through `PortalIndex` and resolves via `roleHome`). Auditors keep their
 * break-glass READ-only super-role.
 */
export function Protected({ children, roles }) {
  const { user, loading } = useAuth();
  const loc = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f6f1e6] text-[#2f4a3a] font-body">
        Loading…
      </div>
    );
  }

  if (!user) {
    // Client-only routes bounce unauthenticated visitors to the patient login;
    // everything else uses the staff/provider login.
    const isClientOnlyRoute =
      Array.isArray(roles) && roles.length === 1 && roles[0] === "client";
    const loginPath = isClientOnlyRoute ? "/login" : "/staff-login";
    return <Navigate to={loginPath} replace state={{ from: loc.pathname }} />;
  }

  if (roles && !roles.includes(user.role)) {
    // Auditor break-glass — allowed anywhere except the client-only patient portal.
    if (user.role === "auditor" && !roles.includes("client")) {
      return children;
    }
    // Route them to their role's proper landing rather than a dead redirect.
    return <Navigate to="/portal" replace />;
  }
  return children;
}

// Named re-export so callers that want to inspect workforce membership can
// pull it straight from this module without touching auth.jsx directly.
export { isWorkforceRole };
