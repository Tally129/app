import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { CheckCircle2, Circle, Search, UserPlus } from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import AddPatientWizard from "../../components/AddPatientWizard";

export default function PatientsList() {
  const { toast } = useToast();
  const [all, setAll] = React.useState([]);
  const [q, setQ] = React.useState("");
  const [showWizard, setShowWizard] = React.useState(false);

  const load = () => api.get("/clients").then((r) => setAll(r.data || []));
  React.useEffect(() => { load(); }, []);

  const filtered = all.filter((c) => {
    const s = q.toLowerCase();
    return !s || (c.full_name || "").toLowerCase().includes(s) ||
           (c.email || "").toLowerCase().includes(s) ||
           (c.mrn || "").toLowerCase().includes(s);
  });

  return (
    <PortalLayout>
      <PortalHeader
        title="Clients"
        subtitle={`${all.length} total`}
        actions={
          <Button onClick={() => setShowWizard(true)} className="btn-lift h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="patients-add-btn">
            <UserPlus size={16} className="mr-2" /> Add client
          </Button>
        }
      />

      <AddPatientWizard open={showWizard} onOpenChange={setShowWizard} onCreated={load} />

      <div className="mb-4 relative max-w-md">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by name, email, or MRN…"
          className="pl-9 bg-[#fbf7ee] border-[#e0d6bc]"
          data-testid="patients-search-input"
        />
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">MRN</th>
              <th className="text-left py-3 px-4">Name</th>
              <th className="text-left py-3 px-4">DOB</th>
              <th className="text-left py-3 px-4">Email</th>
              <th className="text-left py-3 px-4">Phone</th>
              <th className="text-left py-3 px-4">Intake</th>
              <th className="text-right py-3 px-4">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="py-8 text-center text-[#6a6a6a]">No patients</td></tr>
            )}
            {filtered.map((c) => (
              <tr key={c.id} className="border-t border-[#e7dfc9] hover:bg-[#f1ead8]/60" data-testid={`patient-row-${c.id}`}>
                <td className="py-3 px-4 text-[#8a6a3c] text-xs font-mono">{c.mrn || c.id.slice(0, 8).toUpperCase()}</td>
                <td className="py-3 px-4 font-medium text-[#1f2a22]">{c.full_name || "—"}</td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">{c.dob || "—"}</td>
                <td className="py-3 px-4 text-[#3a3a3a]">{c.email || "—"}</td>
                <td className="py-3 px-4 text-[#3a3a3a]">{c.phone || "—"}</td>
                <td className="py-3 px-4">
                  {c.intake_completed ? (
                    <span className="inline-flex items-center gap-1 text-[#2f4a3a] text-xs"><CheckCircle2 size={14} /> Complete</span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[#8a6a3c] text-xs"><Circle size={14} /> Pending</span>
                  )}
                </td>
                <td className="py-3 px-4 text-right">
                  <Link to={`/portal/provider/patients/${c.id}`} className="text-sm text-[#2f4a3a] hover:underline">Open chart</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}
