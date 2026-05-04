import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { ClipboardList, FileText, FolderOpen, CheckCircle2, AlertCircle } from "lucide-react";

export default function PatientDashboard() {
  const { user } = useAuth();
  const [stats, setStats] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    api.get("/dashboard/stats").then((r) => setStats(r.data)).finally(() => setLoading(false));
  }, []);

  return (
    <PortalLayout>
      <PortalHeader
        title={`Welcome, ${user?.full_name?.split(" ")[0] || "Friend"}`}
        subtitle="Your holistic care dashboard"
      />

      {!loading && stats && !stats.intake_completed && (
        <div className="mb-6 rounded-2xl border border-[#c19a4b] bg-[#fbf2d9] p-5 flex items-start gap-3">
          <AlertCircle className="text-[#8a6a3c] mt-0.5 shrink-0" size={20} />
          <div className="flex-1">
            <div className="font-medium text-[#1f2a22]">Finish your intake</div>
            <p className="text-sm text-[#5a5a5a] mt-1">
              Complete your holistic health questionnaire so Dr. Ravello can tailor your plan.
            </p>
          </div>
          <Link to="/portal/patient/intake">
            <Button className="btn-lift h-10 px-5 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
              Start intake
            </Button>
          </Link>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Intake"
          value={
            loading ? "—" : stats?.intake_completed ? (
              <span className="inline-flex items-center gap-2 text-[#2f4a3a]">
                <CheckCircle2 size={24} /> Complete
              </span>
            ) : (
              "Incomplete"
            )
          }
          icon={ClipboardList}
        />
        <StatCard label="Visit notes" value={loading ? "—" : stats?.notes ?? 0} icon={FileText} />
        <StatCard label="Files" value={loading ? "—" : stats?.files ?? 0} icon={FolderOpen} />
      </div>

      <div className="grid md:grid-cols-2 gap-4 mt-6">
        <Link to="/portal/patient/intake" className="card-hover rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 block">
          <div className="flex items-center gap-3">
            <ClipboardList className="text-[#2f4a3a]" />
            <div>
              <div className="font-medium">Health intake</div>
              <div className="text-sm text-[#6a6a6a]">Update your demographics, history, symptoms, lifestyle & consent.</div>
            </div>
          </div>
        </Link>
        <Link to="/portal/patient/chart" className="card-hover rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 block">
          <div className="flex items-center gap-3">
            <FileText className="text-[#2f4a3a]" />
            <div>
              <div className="font-medium">My chart</div>
              <div className="text-sm text-[#6a6a6a]">View Dr. Ravello’s notes & treatment plan.</div>
            </div>
          </div>
        </Link>
        <Link to="/portal/patient/files" className="card-hover rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 block">
          <div className="flex items-center gap-3">
            <FolderOpen className="text-[#2f4a3a]" />
            <div>
              <div className="font-medium">Files & labs</div>
              <div className="text-sm text-[#6a6a6a]">Securely upload labs or download reports.</div>
            </div>
          </div>
        </Link>
        <Link to="/portal/patient/security" className="card-hover rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 block">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="text-[#2f4a3a]" />
            <div>
              <div className="font-medium">Account & security</div>
              <div className="text-sm text-[#6a6a6a]">Enable two-factor authentication.</div>
            </div>
          </div>
        </Link>
      </div>
    </PortalLayout>
  );
}
