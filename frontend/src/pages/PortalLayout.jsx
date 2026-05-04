import React from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import Logo from "../components/Logo";
import { Button } from "../components/ui/button";
import {
  LayoutDashboard,
  Users,
  FileText,
  FolderOpen,
  ClipboardList,
  ShieldCheck,
  LogOut,
  UserCog,
  Activity,
  Menu,
  X,
} from "lucide-react";

const NAV = {
  client: [
    { to: "/portal/patient", label: "Dashboard", icon: LayoutDashboard },
    { to: "/portal/patient/intake", label: "Intake", icon: ClipboardList },
    { to: "/portal/patient/chart", label: "My Chart", icon: FileText },
    { to: "/portal/patient/files", label: "Files", icon: FolderOpen },
    { to: "/portal/patient/security", label: "Security", icon: ShieldCheck },
  ],
  practitioner: [
    { to: "/portal/provider", label: "Dashboard", icon: LayoutDashboard },
    { to: "/portal/provider/patients", label: "Patients", icon: Users },
    { to: "/portal/provider/security", label: "Security", icon: ShieldCheck },
  ],
  staff: [
    { to: "/portal/provider", label: "Dashboard", icon: LayoutDashboard },
    { to: "/portal/provider/patients", label: "Patients", icon: Users },
    { to: "/portal/provider/security", label: "Security", icon: ShieldCheck },
  ],
  admin: [
    { to: "/portal/admin", label: "Overview", icon: LayoutDashboard },
    { to: "/portal/admin/users", label: "Users & Roles", icon: UserCog },
    { to: "/portal/admin/audit", label: "Audit Log", icon: Activity },
    { to: "/portal/provider/patients", label: "Patients", icon: Users },
    { to: "/portal/admin/security", label: "Security", icon: ShieldCheck },
  ],
};

export default function PortalLayout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const items = NAV[user?.role] || [];

  const doLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-parchment font-body text-[#2a2a2a]">
      <div className="top-ribbon" />

      {/* HIPAA DEMO BANNER */}
      <div className="bg-[#7a2a2a] text-[#f6f1e6] text-[11px] tracking-widest uppercase text-center py-1.5 px-4">
        DEMO ENVIRONMENT · NOT HIPAA COMPLIANT · DO NOT ENTER REAL PHI
      </div>

      <div className="flex">
        {/* Sidebar */}
        <aside
          className={`${
            open ? "translate-x-0" : "-translate-x-full"
          } md:translate-x-0 fixed md:sticky top-0 z-30 md:z-10 h-screen md:h-[calc(100vh-34px)] w-64 bg-[#fbf7ee] border-r border-[#e7dfc9] flex flex-col transition-transform`}
        >
          <div className="p-5 border-b border-[#e7dfc9] flex items-center justify-between">
            <Link to="/portal" className="block">
              <Logo size={56} withText={false} />
            </Link>
            <button className="md:hidden text-[#2f4a3a]" onClick={() => setOpen(false)}>
              <X size={20} />
            </button>
          </div>
          <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
            {items.map((it) => {
              const Icon = it.icon;
              return (
                <NavLink
                  key={it.to}
                  to={it.to}
                  end={it.to === "/portal/patient" || it.to === "/portal/provider" || it.to === "/portal/admin"}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition ${
                      isActive
                        ? "bg-[#2f4a3a] text-[#f6f1e6]"
                        : "text-[#3a3a3a] hover:bg-[#f1ead8]"
                    }`
                  }
                >
                  <Icon size={16} />
                  {it.label}
                </NavLink>
              );
            })}
          </nav>
          <div className="p-4 border-t border-[#e7dfc9]">
            <div className="text-xs text-[#6a6a6a] truncate">{user?.email}</div>
            <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c] mt-0.5">
              {user?.role}
            </div>
            <Button
              onClick={doLogout}
              variant="outline"
              className="mt-3 w-full h-9 rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6]"
            >
              <LogOut size={14} className="mr-2" /> Sign out
            </Button>
          </div>
        </aside>

        {/* Main */}
        <div className="flex-1 min-w-0">
          <div className="md:hidden p-3 border-b border-[#e7dfc9] bg-[#fbf7ee] flex items-center justify-between">
            <button onClick={() => setOpen(true)} className="text-[#2f4a3a]">
              <Menu size={22} />
            </button>
            <Logo size={34} withText={false} />
            <button onClick={doLogout} className="text-[#2f4a3a]">
              <LogOut size={18} />
            </button>
          </div>
          <main className="p-6 md:p-10 max-w-6xl mx-auto page-fade">{children}</main>
        </div>
      </div>
    </div>
  );
}

export function PortalHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3 mb-8">
      <div>
        <h1 className="font-display text-[34px] md:text-[42px] text-[#1f2a22] leading-tight">
          {title}
        </h1>
        {subtitle && <p className="text-[#6a6a6a] mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, icon: Icon, accent }) {
  return (
    <div className="card-hover rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-widest text-[#8a6a3c]">{label}</span>
        {Icon && <Icon size={16} className="text-[#2f4a3a]" />}
      </div>
      <div className={`font-display text-[36px] mt-2 ${accent || "text-[#1f2a22]"}`}>{value}</div>
    </div>
  );
}
