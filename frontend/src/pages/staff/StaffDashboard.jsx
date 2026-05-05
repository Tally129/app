import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import {
  Briefcase, UserPlus, Users, ShoppingCart, Boxes, Timer,
  AlertTriangle, Calendar, ChevronRight, PlayCircle,
  CalendarDays, Receipt, Building2,
} from "lucide-react";

/**
 * Staff dashboard — front-desk-first. Replaces the practitioner dashboard for staff role.
 * NO clinical content (no SOAP, no labs, no prescriptions). Heavy on operations:
 *   - Today's queue (live)
 *   - Walk-in / check-in shortcut
 *   - Unbooked time alerts
 *   - Inventory exceptions (low-stock + expiring)
 *   - Time-clock card
 *   - POS quick-launch
 */
export default function StaffDashboard() {
  const [today, setToday] = React.useState([]);
  const [appts, setAppts] = React.useState([]);
  const [inventory, setInventory] = React.useState([]);
  const [expiring, setExpiring] = React.useState([]);
  const [shifts, setShifts] = React.useState([]);
  const [todayTxnTotal, setTodayTxnTotal] = React.useState(0);
  const [todayTxnCount, setTodayTxnCount] = React.useState(0);

  const load = async () => {
    try {
      const [v, a, i, e, s, t] = await Promise.all([
        api.get("/front-desk/today").catch(() => ({ data: [] })),
        api.get("/appointments").catch(() => ({ data: [] })),
        api.get("/inventory").catch(() => ({ data: [] })),
        api.get("/inventory/expiring?days=60").catch(() => ({ data: [] })),
        api.get("/time-clock/me").catch(() => ({ data: [] })),
        api.get("/transactions?limit=200").catch(() => ({ data: [] })),
      ]);
      setToday(v.data || []);
      setAppts(a.data || []);
      setInventory(i.data || []);
      setExpiring(e.data || []);
      setShifts(s.data || []);
      const startOfDay = new Date(); startOfDay.setHours(0, 0, 0, 0);
      const todayTxns = (t.data || []).filter((x) => x.created_at && new Date(x.created_at) >= startOfDay);
      setTodayTxnTotal(todayTxns.reduce((sum, x) => sum + (x.total || 0), 0));
      setTodayTxnCount(todayTxns.length);
    } catch {}
  };
  React.useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t); }, []);

  const lowStock = inventory.filter((i) => (i.stock || 0) <= (i.low_stock_threshold || 5));
  const inClinic = today.filter((v) => v.status === "checked_in" || v.status === "in_room").length;
  const walkIns = today.filter((v) => v.walk_in).length;
  const completed = today.filter((v) => v.status === "checked_out").length;

  // Next 4 appointments today (any mode)
  const dayStart = new Date(); dayStart.setHours(0, 0, 0, 0);
  const dayEnd = new Date(); dayEnd.setHours(23, 59, 59, 999);
  const todaysAppts = appts
    .filter((a) => a.start && new Date(a.start) >= dayStart && new Date(a.start) <= dayEnd)
    .sort((a, b) => new Date(a.start) - new Date(b.start));
  const upNext = todaysAppts
    .filter((a) => new Date(a.start) >= new Date() && !["completed", "canceled"].includes(a.status))
    .slice(0, 4);

  // Open shift?
  const openShift = (shifts || []).find((e) => !e.clock_out);

  return (
    <PortalLayout>
      <PortalHeader
        title="Front desk"
        subtitle={new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
        actions={
          <div className="flex gap-2">
            <Link to="/portal/staff/front-desk">
              <Button className="h-9 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="staff-checkin-btn">
                <UserPlus size={14} className="mr-1" /> Check in / Walk-in
              </Button>
            </Link>
            <Link to="/portal/staff/pos">
              <Button variant="outline" className="h-9 rounded-full border-[#c19a4b] text-[#8a6a3c]" data-testid="staff-pos-btn">
                <ShoppingCart size={14} className="mr-1" /> Open POS
              </Button>
            </Link>
          </div>
        }
      />

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard label="In clinic" value={inClinic} icon={Users} />
        <StatCard label="Walk-ins today" value={walkIns} icon={Building2} />
        <StatCard label="Completed visits" value={completed} icon={Calendar} />
        <StatCard label="Today's revenue" value={`$${todayTxnTotal.toFixed(0)}`} icon={Receipt} />
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-8">
        {/* Up Next */}
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5" data-testid="staff-upnext">
          <div className="flex items-center justify-between mb-4">
            <div className="eyebrow text-[#8a6a3c]">Up next today</div>
            <Link to="/portal/staff/appointments" className="text-xs text-[#2f4a3a] hover:underline inline-flex items-center gap-1">
              View schedule <ChevronRight size={11} />
            </Link>
          </div>
          {upNext.length === 0 ? (
            <div className="text-sm text-[#6a6a6a] py-6 text-center">No more visits today. 🌿</div>
          ) : (
            <ul className="divide-y divide-[#e7dfc9]">
              {upNext.map((a) => (
                <li key={a.id} className="py-3 flex items-center gap-3">
                  <div className="w-14 text-center">
                    <div className="font-display text-lg text-[#1f2a22]">
                      {new Date(a.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-[#1f2a22] truncate">{a.client_name || "—"}</div>
                    <div className="text-xs text-[#6a6a6a] flex items-center gap-2 mt-0.5">
                      {a.visit_mode === "telehealth" ? "Telehealth" : "In clinic"}
                      <span>·</span>
                      <span>{a.visit_type || "Visit"}</span>
                    </div>
                  </div>
                  {a.visit_mode === "telehealth" ? (
                    <Link to={`/portal/visit/${a.id}`}>
                      <Button size="sm" variant="outline" className="rounded-full text-xs border-[#2f4a3a] text-[#2f4a3a]">
                        <PlayCircle size={11} className="mr-1" /> Open
                      </Button>
                    </Link>
                  ) : (
                    <Link to="/portal/staff/front-desk">
                      <Button size="sm" variant="outline" className="rounded-full text-xs border-[#c19a4b] text-[#8a6a3c]">
                        Check in
                      </Button>
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Time clock card */}
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5" data-testid="staff-timeclock-card">
          <div className="flex items-center justify-between mb-4">
            <div className="eyebrow text-[#8a6a3c]">My shift</div>
            <Link to="/portal/staff/time-clock" className="text-xs text-[#2f4a3a] hover:underline inline-flex items-center gap-1">
              Time clock <ChevronRight size={11} />
            </Link>
          </div>
          {openShift ? (
            <div>
              <div className="font-display text-3xl text-[#2f4a3a]">On shift</div>
              <div className="text-xs text-[#6a6a6a] mt-1">
                Started at {new Date(openShift.clock_in).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
              </div>
              <Link to="/portal/staff/time-clock">
                <Button variant="outline" className="mt-4 rounded-full h-9 border-[#7a2a2a] text-[#7a2a2a]">
                  <Timer size={12} className="mr-1" /> Manage shift
                </Button>
              </Link>
            </div>
          ) : (
            <div>
              <div className="font-display text-3xl text-[#8a6a3c]">Clocked out</div>
              <Link to="/portal/staff/time-clock">
                <Button className="mt-4 rounded-full h-9 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
                  <Timer size={12} className="mr-1" /> Punch in
                </Button>
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* Exceptions row */}
      <div className="grid lg:grid-cols-2 gap-6">
        <ExceptionCard
          title="Low stock"
          count={lowStock.length}
          tone={lowStock.length > 0 ? "warn" : "ok"}
          icon={Boxes}
          link="/portal/staff/inventory"
          rows={lowStock.slice(0, 5).map((i) => ({ left: i.name, right: `${i.stock} left` }))}
          empty="All items above threshold."
          testid="staff-low-stock"
        />
        <ExceptionCard
          title="Expiring soon"
          count={expiring.length}
          tone={expiring.length > 0 ? "alert" : "ok"}
          icon={AlertTriangle}
          link="/portal/staff/inventory"
          rows={expiring.slice(0, 5).map((i) => ({ left: i.name, right: i.expiring_lot?.expires_on || "—" }))}
          empty="No lots expiring within 60 days."
          testid="staff-expiring"
        />
      </div>

      <div className="mt-8 grid sm:grid-cols-3 gap-3">
        <QuickLink to="/portal/staff/appointments" icon={CalendarDays} label="Schedule" />
        <QuickLink to="/portal/staff/patients" icon={Users} label="Clients" />
        <QuickLink to="/portal/staff/transactions" icon={Receipt} label="Transactions" />
      </div>
    </PortalLayout>
  );
}

function ExceptionCard({ title, count, tone, icon: Icon, link, rows, empty, testid }) {
  const colorMap = {
    ok: "border-[#e7dfc9] text-[#5b6f5b]",
    warn: "border-[#c19a4b] text-[#8a6a3c]",
    alert: "border-[#7a2a2a] text-[#7a2a2a]",
  };
  return (
    <div className={`rounded-2xl border-2 ${colorMap[tone]} bg-[#fbf7ee] p-5`} data-testid={testid}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon size={16} />
          <span className="eyebrow">{title}</span>
        </div>
        <span className="font-display text-2xl">{count}</span>
      </div>
      {rows.length === 0 ? (
        <div className="text-sm text-[#6a6a6a]">{empty}</div>
      ) : (
        <ul className="text-sm space-y-1">
          {rows.map((r, i) => (
            <li key={i} className="flex justify-between text-[#3a3a3a]">
              <span className="truncate">{r.left}</span>
              <span className="text-xs">{r.right}</span>
            </li>
          ))}
        </ul>
      )}
      <Link to={link} className="mt-3 inline-flex items-center gap-1 text-xs hover:underline">
        Open inventory <ChevronRight size={11} />
      </Link>
    </div>
  );
}

function QuickLink({ to, icon: Icon, label }) {
  return (
    <Link to={to} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4 hover:bg-[#f1ead8] transition flex items-center gap-3">
      <Icon size={18} className="text-[#2f4a3a]" />
      <span className="text-sm font-medium text-[#1f2a22]">{label}</span>
      <ChevronRight size={14} className="ml-auto text-[#8a6a3c]" />
    </Link>
  );
}
