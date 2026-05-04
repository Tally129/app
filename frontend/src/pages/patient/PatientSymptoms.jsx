import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea } from "recharts";
import { Activity, Plus } from "lucide-react";

export default function PatientSymptoms() {
  const { toast } = useToast();
  const [presets, setPresets] = React.useState([]);
  const [logs, setLogs] = React.useState([]);
  const [form, setForm] = React.useState({ symptom: "", severity: 5, note: "" });

  const load = React.useCallback(() => api.get("/symptom-logs").then((r) => setLogs(r.data || [])), []);
  React.useEffect(() => {
    api.get("/symptoms/presets").then((r) => {
      setPresets(r.data.symptoms);
      setForm((f) => ({ ...f, symptom: r.data.symptoms[0] }));
    });
    load();
  }, [load]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.symptom) return;
    try {
      await api.post("/symptom-logs", form);
      toast({ title: "Logged", description: `${form.symptom}: ${form.severity}/10` });
      setForm({ ...form, note: "" });
      load();
    } catch { toast({ title: "Failed" }); }
  };

  // Group by symptom -> timeseries
  const byName = React.useMemo(() => {
    const g = {};
    for (const l of logs) {
      (g[l.symptom] = g[l.symptom] || []).push({
        t: new Date(l.logged_at).getTime(),
        date: new Date(l.logged_at).toLocaleDateString(),
        severity: l.severity,
        note: l.note,
      });
    }
    return g;
  }, [logs]);

  return (
    <PortalLayout>
      <PortalHeader title="Symptom Tracker" subtitle="Log daily or weekly to visualize how you’re feeling over time." />

      <form onSubmit={submit} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 grid md:grid-cols-4 gap-3 mb-8">
        <div>
          <Label>Symptom</Label>
          <Select value={form.symptom} onValueChange={(v) => setForm({ ...form, symptom: v })}>
            <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
            <SelectContent>{presets.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div>
          <Label>Severity (1–10): {form.severity}</Label>
          <input type="range" min={1} max={10} value={form.severity} onChange={(e) => setForm({ ...form, severity: Number(e.target.value) })} className="mt-4 w-full accent-[#2f4a3a]" />
        </div>
        <div className="md:col-span-2">
          <Label>Note (optional)</Label>
          <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="How you’re feeling today" />
        </div>
        <div className="md:col-span-4 flex justify-end">
          <Button type="submit" className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"><Plus size={14} className="mr-2" /> Add entry</Button>
        </div>
      </form>

      {Object.keys(byName).length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <Activity size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No entries yet. Log a symptom above to see your trends.</div>
        </div>
      ) : (
        <div className="space-y-5">
          {Object.entries(byName).map(([name, data]) => (
            <div key={name} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="flex items-center justify-between mb-2">
                <div className="font-display text-xl text-[#1f2a22]">{name}</div>
                <div className="text-xs text-[#6a6a6a]">{data.length} entries</div>
              </div>
              <div style={{ width: "100%", height: 180 }}>
                <ResponsiveContainer>
                  <LineChart data={data} margin={{ top: 10, right: 16, bottom: 10, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e7dfc9" />
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6a6a6a" }} />
                    <YAxis domain={[1, 10]} tick={{ fontSize: 11, fill: "#6a6a6a" }} />
                    <Tooltip contentStyle={{ background: "#fbf7ee", border: "1px solid #e7dfc9", borderRadius: 8, fontSize: 12 }} />
                    <Line type="monotone" dataKey="severity" stroke="#2f4a3a" strokeWidth={2} dot={{ r: 4, fill: "#c19a4b" }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ))}
        </div>
      )}
    </PortalLayout>
  );
}
