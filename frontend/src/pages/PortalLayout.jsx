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
  CalendarDays,
  Clock,
  Receipt,
  Bell,
  Sparkles,
  LineChart,
  TestTube2,
  MessageSquare,
  Video,
  ShoppingCart,
  Boxes,
  Stethoscope,
  Timer,
  Upload,
  Wallet,
  Briefcase,
  UserCircle,
  BarChart3,
  Home,
} from "lucide-react";

// =============== NAV CONFIG (grouped) ===============
const NAV = {
  client: [
    {
      group: "Today",
      items: [
        { to: "/portal/patient", label: "Dashboard", icon: LayoutDashboard },
        { to: "/portal/patient/appointments", label: "Appointments", icon: CalendarDays },
        { to: "/portal/patient/messages", label: "Messages", icon: MessageSquare, badge: "messages" },
      ],
    },
    {
      group: "My Health",
      items: [
        { to: "/portal/patient/intake", label: "Intake", icon: ClipboardList },
        { to: "/portal/patient/chart", label: "My Chart", icon: FileText },
        { to: "/portal/patient/telehealth", label: "Telehealth", icon: Video },
        { to: "/portal/patient/plan", label: "Treatment Plan", icon: Sparkles },
        { to: "/portal/patient/protocols", label: "Protocols", icon: Activity },
        { to: "/portal/patient/symptoms", label: "Symptom Tracker", icon: LineChart },
        { to: "/portal/patient/labs", label: "Lab Results", icon: TestTube2 },
        { to: "/portal/patient/files", label: "Files", icon: FolderOpen },
        { to: "/portal/patient/billing", label: "Billing", icon: Receipt },
      ],
    },
    {
      group: "Settings",
      items: [
        { to: "/portal/patient/account", label: "My Account", icon: UserCircle },
        { to: "/portal/patient/security", label: "Security", icon: ShieldCheck },
      ],
    },
  ],

  practitioner: [
    {
      group: "Today",
      items: [
        { to: "/portal/provider", label: "Dashboard", icon: LayoutDashboard },
        { to: "/portal/provider/front-desk", label: "Front Desk", icon: Briefcase },
        { to: "/portal/provider/appointments", label: "Appointments", icon: CalendarDays },
        { to: "/portal/provider/time-clock", label: "Time Clock", icon: Timer },
      ],
    },
    {
      group: "Clients",
      items: [
        { to: "/portal/provider/patients", label: "Clients", icon: Users },
        { to: "/portal/provider/messages", label: "Messages", icon: MessageSquare, badge: "messages" },
      ],
    },
    {
      group: "Operations",
      items: [
        { to: "/portal/provider/availability", label: "Availability", icon: Clock },
        { to: "/portal/provider/treatments", label: "Treatments", icon: Stethoscope },
        { to: "/portal/provider/soap", label: "SOAP Notes", icon: FileText },
        { to: "/portal/provider/protocols", label: "Protocols", icon: Activity },
        { to: "/portal/provider/forms", label: "Forms & Consents", icon: ClipboardList },
        { to: "/portal/provider/library", label: "Document Library", icon: FolderOpen },
        { to: "/portal/provider/analytics", label: "Analytics", icon: BarChart3 },
      ],
    },
    {
      group: "Settings",
      items: [
        { to: "/portal/provider/account", label: "My Account", icon: UserCircle },
        { to: "/portal/provider/security", label: "Security", icon: ShieldCheck },
      ],
    },
  ],

  staff: [
    {
      group: "Today",
      items: [
        { to: "/portal/staff", label: "Front desk", icon: Briefcase },
        { to: "/portal/staff/appointments", label: "Appointments", icon: CalendarDays },
        { to: "/portal/staff/telehealth", label: "Telehealth", icon: Video },
        { to: "/portal/staff/time-clock", label: "Time Clock", icon: Timer },
      ],
    },
    {
      group: "Clients",
      items: [
        { to: "/portal/staff/patients", label: "Clients", icon: Users },
      ],
    },
    {
      group: "Operations",
      items: [
        { to: "/portal/staff/pos", label: "Point of Sale", icon: ShoppingCart },
        { to: "/portal/staff/transactions", label: "Transactions", icon: Wallet },
        { to: "/portal/staff/inventory", label: "Inventory", icon: Boxes },
        { to: "/portal/staff/treatments", label: "Treatments", icon: Stethoscope },
        { to: "/portal/staff/soap", label: "SOAP Notes", icon: FileText },
        { to: "/portal/staff/protocols", label: "Protocols", icon: Activity },
        { to: "/portal/staff/forms", label: "Forms & Consents", icon: ClipboardList },
        { to: "/portal/staff/library", label: "Document Library", icon: FolderOpen },
      ],
    },
    {
      group: "Settings",
      items: [
        { to: "/portal/staff/account", label: "My Account", icon: UserCircle },
        { to: "/portal/staff/security", label: "Security", icon: ShieldCheck },
      ],
    },
  ],

  admin: [
    {
      group: "Today",
      items: [
        { to: "/portal/admin", label: "Overview", icon: LayoutDashboard },
        { to: "/portal/admin/front-desk", label: "Front Desk", icon: Briefcase },
        { to: "/portal/provider/appointments", label: "Appointments", icon: CalendarDays },
        { to: "/portal/admin/telehealth", label: "Telehealth", icon: Video },
        { to: "/portal/admin/time-clock", label: "Time Clock", icon: Timer },
      ],
    },
    {
      group: "Clients",
      items: [
        { to: "/portal/provider/patients", label: "Clients", icon: Users },
        { to: "/portal/admin/import-clients", label: "Import Clients", icon: Upload },
      ],
    },
    {
      group: "Operations",
      items: [
        { to: "/portal/admin/pos", label: "Point of Sale", icon: ShoppingCart },
        { to: "/portal/admin/transactions", label: "Transactions", icon: Wallet },
        { to: "/portal/admin/inventory", label: "Inventory", icon: Boxes },
        { to: "/portal/admin/treatments", label: "Treatments", icon: Stethoscope },
        { to: "/portal/admin/soap", label: "SOAP Notes", icon: FileText },
        { to: "/portal/admin/protocols", label: "Protocols", icon: Activity },
        { to: "/portal/admin/forms", label: "Forms & Consents", icon: ClipboardList },
        { to: "/portal/admin/library", label: "Document Library", icon: FolderOpen },
        { to: "/portal/admin/analytics", label: "Analytics", icon: BarChart3 },
      ],
    },
    {
      group: "Settings",
      items: [
        { to: "/portal/admin/users", label: "Users & Roles", icon: UserCog },
        { to: "/portal/admin/reminders", label: "Reminders", icon: Bell },
        { to: "/portal/admin/audit", label: "Audit Log", icon: Activity },
        { to: "/portal/admin/compliance", label: "HIPAA Compliance", icon: ShieldCheck },
        { to: "/portal/admin/account", label: "My Account", icon: UserCircle },
        { to: "/portal/admin/security", label: "Security", icon: ShieldCheck },
      ],
    },
  ],
};

const HOME_ROUTES = new Set(["/portal/patient", "/portal/provider", "/portal/admin"]);

export default function PortalLayout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const [unread, setUnread] = React.useState(0);
  const groups = NAV[user?.role] || [];

  React.useEffect(() => {
    if (!user) return;
    let active = true;
    const fetchUnread = async () => {
      try {
        const r = await (await import("../lib/api")).default.get("/messages/unread-count");
        if (active) setUnread(r.data?.count || 0);
      } catch {}
    };
    fetchUnread();
    const t = setInterval(fetchUnread, 30_000);
    // Best-effort PWA push subscription (silent failure)
    import("../lib/push").then(({ ensurePushSubscription }) => ensurePushSubscription()).catch(() => {});
    return () => { active = false; clearInterval(t); };
  }, [user]);

  const doLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-parchment font-body text-[#2a2a2a]" data-testid="portal-layout">
      <div className="top-ribbon" />

      <div className="flex">
        {/* Sidebar */}
        <aside
          className={`${
            open ? "translate-x-0" : "-translate-x-full"
          } md:translate-x-0 fixed md:sticky top-0 z-30 md:z-10 h-screen md:h-[calc(100vh-34px)] w-64 bg-[#fbf7ee] border-r border-[#e7dfc9] flex flex-col transition-transform`}
          data-testid="portal-sidebar"
        >
          <div className="p-5 border-b border-[#e7dfc9] flex items-center justify-between">
            <Link to="/portal" className="block">
              <Logo size={56} withText={false} />
            </Link>
            <button
              className="md:hidden text-[#2f4a3a]"
              onClick={() => setOpen(false)}
              data-testid="sidebar-close-btn"
            >
              <X size={20} />
            </button>
          </div>
          <nav className="flex-1 p-3 space-y-4 overflow-y-auto" data-testid="portal-nav">
            {groups.map((grp) => (
              <div key={grp.group} data-testid={`nav-group-${grp.group.toLowerCase().replace(/\s+/g, "-")}`}>
                <div className="px-3 pt-1 pb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#8a6a3c]">
                  {grp.group}
                </div>
                <div className="space-y-0.5">
                  {grp.items.map((it) => {
                    const Icon = it.icon;
                    return (
                      <NavLink
                        key={it.to}
                        to={it.to}
                        end={HOME_ROUTES.has(it.to)}
                        onClick={() => setOpen(false)}
                        data-testid={`nav-link-${it.label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
                        className={({ isActive }) =>
                          `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition ${
                            isActive
                              ? "bg-[#2f4a3a] text-[#f6f1e6]"
                              : "text-[#3a3a3a] hover:bg-[#f1ead8]"
                          }`
                        }
                      >
                        <Icon size={15} />
                        <span className="flex-1">{it.label}</span>
                        {it.badge === "messages" && unread > 0 && (
                          <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-[#c19a4b] text-[#1f2a22] text-[10px] font-semibold">
                            {unread}
                          </span>
                        )}
                      </NavLink>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
          <div className="p-4 border-t border-[#e7dfc9]">
            <div className="text-xs text-[#6a6a6a] truncate" data-testid="sidebar-user-email">{user?.email}</div>
            <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c] mt-0.5" data-testid="sidebar-user-role">
              {user?.role}
            </div>
            <Button
              onClick={doLogout}
              variant="outline"
              className="mt-3 w-full h-9 rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6]"
              data-testid="sidebar-logout-btn"
            >
              <LogOut size={14} className="mr-2" /> Sign out
            </Button>
          </div>
        </aside>

        {/* Main */}
        <div className="flex-1 min-w-0">
          <div className="md:hidden p-3 border-b border-[#e7dfc9] bg-[#fbf7ee] flex items-center justify-between">
            <button onClick={() => setOpen(true)} className="text-[#2f4a3a]" data-testid="sidebar-open-btn">
              <Menu size={22} />
            </button>
            <Logo size={34} withText={false} />
            <button onClick={doLogout} className="text-[#2f4a3a]" data-testid="mobile-logout-btn">
              <LogOut size={18} />
            </button>
          </div>
          <main className="p-6 md:p-10 max-w-6xl mx-auto page-fade pb-24 md:pb-10">{children}</main>
        </div>
      </div>

      {/* Mobile bottom nav (PWA-style) for clients only */}
      {user?.role === "client" && (
        <nav
          className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-[#fbf7ee] border-t border-[#e7dfc9] flex justify-around py-2 pb-[env(safe-area-inset-bottom)]"
          data-testid="mobile-bottom-nav"
        >
          <BottomLink to="/portal/patient" icon={Home} label="Home" exact />
          <BottomLink to="/portal/patient/appointments" icon={CalendarDays} label="Visits" />
          <BottomLink to="/portal/patient/messages" icon={MessageSquare} label="Messages" badge={unread} />
          <BottomLink to="/portal/patient/chart" icon={FileText} label="Chart" />
          <BottomLink to="/portal/patient/account" icon={UserCircle} label="Me" />
        </nav>
      )}
    </div>
  );
}

function BottomLink({ to, icon: Icon, label, exact, badge }) {
  return (
    <NavLink
      to={to}
      end={exact}
      className={({ isActive }) =>
        `flex flex-col items-center gap-0.5 flex-1 py-1 text-[10px] uppercase tracking-wider relative ${
          isActive ? "text-[#2f4a3a]" : "text-[#6a6a6a]"
        }`
      }
      data-testid={`mobile-nav-${label.toLowerCase()}`}
    >
      <Icon size={20} />
      <span>{label}</span>
      {badge > 0 && (
        <span className="absolute top-0 right-1/4 inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 rounded-full bg-[#c19a4b] text-[#1f2a22] text-[9px] font-semibold">
          {badge}
        </span>
      )}
    </NavLink>
  );
}

export function PortalHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3 mb-8">
      <div>
        <h1 className="font-display text-[34px] md:text-[42px] text-[#1f2a22] leading-tight" data-testid="page-title">
          {title}
        </h1>
        {subtitle && <p className="text-[#6a6a6a] mt-1" data-testid="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2 flex-wrap">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, icon: Icon, accent, to }) {
  const card = (
    <div className="card-hover rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 h-full">
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-widest text-[#8a6a3c]">{label}</span>
        {Icon && <Icon size={16} className="text-[#2f4a3a]" />}
      </div>
      <div className={`font-display text-[36px] mt-2 ${accent || "text-[#1f2a22]"}`}>{value}</div>
    </div>
  );
  if (to) {
    return (
      <Link
        to={to}
        className="block transition hover:-translate-y-0.5"
        data-testid={`statcard-link-${(label || "").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
      >
        {card}
      </Link>
    );
  }
  return card;
}

