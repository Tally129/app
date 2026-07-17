import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./auth";

/**
 * Route guard.
 * - `roles` = strict allowlist for full access.
 * - The break-glass `auditor` role is treated as a read-only super-role:
 *   it is allowed to enter ANY protected admin/practitioner/staff route.
 *   The backend still enforces GET-only + emergency=true audit stamping on
 *   every request, so surface here is safe.
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
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (roles && !roles.includes(user.role)) {
    // Auditor break-glass — allowed anywhere except the client-only patient portal
    if (user.role === "auditor" && !roles.includes("client")) {
      return children;
    }
    return <Navigate to="/portal" replace />;
  }
  return children;
}
