import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { CheckCircle2, Circle, Search, UserPlus } from "lucide-react";
import { useToast } from "../../hooks/use-toast";

export default function PatientsList() {
  const { toast } = useToast();
  const [all, setAll] = React.useState([]);
  const [q, setQ] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [newPt, setNewPt] = React.useState({ full_name: "", email: "", phone: "" });

  const load = () => api.get("/clients").then((r) => setAll(r.data || []));
  React.useEffect(() => { load(); }, []);

  const create = async () => {
    if (!newPt.full_name) { toast({ title: "Name required" }); return; }
    try {
      await api.post("/clients", newPt);
      toast({ title: "Patient added" });
      setCreating(false);
      setNewPt({ full_name: "", email: "", phone: "" });
      load();
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "Try again." });
    }
  };

  const filtered = all.filter((c) => {
    const s = q.toLowerCase();
    return !s || (c.full_name || "").toLowerCase().includes(s) || (c.email || "").toLowerCase().includes(s);
  });

  return (
    <PortalLayout>
      <PortalHeader
        title="Patients"
        subtitle={`${all.length} total`}
        actions={
          <Button onClick={() => setCreating((v) => !v)} className="btn-lift h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
            <UserPlus size={16} className="mr-2" /> New patient
          </Button>
        }
      />

      {creating && (
        <div className="mb-6 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 grid md:grid-cols-4 gap-3">
          <Input placeholder="Full name" className="bg-[#f6f1e6] border-[#e0d6bc]" value={newPt.full_name} onChange={(e) => setNewPt({ ...newPt, full_name: e.target.value })} />
          <Input placeholder="Email" className="bg-[#f6f1e6] border-[#e0d6bc]" value={newPt.email} onChange={(e) => setNewPt({ ...newPt, email: e.target.value })} />
          <Input placeholder="Phone" className="bg-[#f6f1e6] border-[#e0d6bc]" value={newPt.phone} onChange={(e) => setNewPt({ ...newPt, phone: e.target.value })} />
          <Button onClick={create} className="btn-lift rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">Add</Button>
        </div>
      )}

      <div className="mb-4 relative max-w-md">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by name or email"
          className="pl-9 bg-[#fbf7ee] border-[#e0d6bc]"
        />
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Name</th>
              <th className="text-left py-3 px-4">Email</th>
              <th className="text-left py-3 px-4">Phone</th>
              <th className="text-left py-3 px-4">Intake</th>
              <th className="text-right py-3 px-4">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={5} className="py-8 text-center text-[#6a6a6a]">No patients</td></tr>
            )}
            {filtered.map((c) => (
              <tr key={c.id} className="border-t border-[#e7dfc9] hover:bg-[#f1ead8]/60">
                <td className="py-3 px-4 font-medium text-[#1f2a22]">{c.full_name || "—"}</td>
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
