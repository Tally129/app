import React from "react";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { Users, Activity, FileText, FolderOpen, ClipboardList, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

export default function AdminOverview() {
  const [stats, setStats] = React.useState(null);
  React.useEffect(() => {
    api.get("/dashboard/stats").then((r) => setStats(r.data));
  }, []);
  return (
    <PortalLayout>
      <PortalHeader title="Admin Overview" subtitle="System-wide activity" />
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <StatCard label="Clients" value={stats?.clients ?? 0} icon={Users} />
        <StatCard label="Users" value={stats?.users ?? 0} icon={ShieldCheck} />
        <StatCard label="Visit notes" value={stats?.notes ?? 0} icon={FileText} />
        <StatCard label="Files" value={stats?.files ?? 0} icon={FolderOpen} />
        <StatCard label="Appt requests" value={stats?.appointments_requested ?? 0} icon={ClipboardList} />
        <StatCard label="Audit events" value={stats?.audit_events ?? 0} icon={Activity} />
      </div>
      <div className="mt-6 grid md:grid-cols-2 gap-4">
        <Link to="/portal/admin/users" className="card-hover rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 block">
          <div className="eyebrow text-[#8a6a3c]">Manage</div>
          <div className="font-medium mt-2">Users & roles</div>
          <div className="text-sm text-[#6a6a6a]">Invite practitioners, staff, or admins. Change roles.</div>
        </Link>
        <Link to="/portal/admin/audit" className="card-hover rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 block">
          <div className="eyebrow text-[#8a6a3c]">Review</div>
          <div className="font-medium mt-2">Audit log</div>
          <div className="text-sm text-[#6a6a6a]">Immutable record of every PHI access.</div>
        </Link>
      </div>
    </PortalLayout>
  );
}
