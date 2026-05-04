import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth, roleHome } from "../lib/auth";

export default function PortalIndex() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  React.useEffect(() => {
    if (loading) return;
    if (!user) navigate("/login", { replace: true });
    else navigate(roleHome(user.role), { replace: true });
  }, [user, loading, navigate]);
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f6f1e6] text-[#2f4a3a] font-body">
      Redirecting…
    </div>
  );
}
