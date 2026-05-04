import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Users, FileText, CalendarDays } from "lucide-react";

export default function ProviderDashboard() {
  const { user } = useAuth();
  const [stats, setStats] = React.useState(null);
  const [recent, setRecent] = React.useState([]);

  React.useEffect(() => {
    api.get("/dashboard/stats").then((r) => setStats(r.data));
    api.get("/clients").then((r) => setRecent((r.data || []).slice(0, 8)));
  }, []);

  return (
    <PortalLayout>
      <PortalHeader
        title={`Good to see you, ${user?.full_name?.split(" ").slice(-1)[0] || "Doctor"}`}
        subtitle="Your clinical workspace"
      />

      <div className="grid sm:grid-cols-3 gap-4 mb-8">
        <StatCard label="My patients" value={stats?.my_patients ?? 0} icon={Users} />
        <StatCard label="Total patients" value={stats?.total_clients ?? 0} icon={Users} />
        <StatCard label="Notes authored" value={stats?.my_notes ?? 0} icon={FileText} />
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="eyebrow text-[#8a6a3c]">Recent patients</div>
          <Link to="/portal/provider/patients" className="text-sm text-[#2f4a3a] hover:underline">
            View all →
          </Link>
        </div>
        {recent.length === 0 ? (
          <div className="text-[#6a6a6a] text-sm">No patients yet.</div>
        ) : (
          <ul className="divide-y divide-[#e7dfc9]">
            {recent.map((c) => (
              <li key={c.id} className="py-3 flex items-center justify-between">
                <div>
                  <div className="font-medium text-[#1f2a22]">{c.full_name || "—"}</div>
                  <div className="text-xs text-[#6a6a6a]">
                    {c.email || "no email"} · intake {c.intake_completed ? "complete" : "pending"}
                  </div>
                </div>
                <Link
                  to={`/portal/provider/patients/${c.id}`}
                  className="text-sm text-[#2f4a3a] hover:underline"
                >
                  Open chart
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </PortalLayout>
  );
}
