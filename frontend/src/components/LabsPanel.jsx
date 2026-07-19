import React from "react";
import api from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Textarea } from "./ui/textarea";
import { useToast } from "../hooks/use-toast";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea } from "recharts";
import { Plus, Trash2 } from "lucide-react";
import { getErrorMessage } from "../lib/errors";

export default function LabsPanel({ clientId }) {
  const { toast } = useToast();
  const [labs, setLabs] = React.useState([]);
  const [presets, setPresets] = React.useState([]);
  const [form, setForm] = React.useState({
    test_name: "",
    value: "",
    unit: "",
    reference_low: "",
    reference_high: "",
    measured_at: new Date().toISOString().slice(0, 10),
    notes: "",
  });

  const load = React.useCallback(() => {
    api.get("/lab-values", { params: { client_id: clientId } }).then((r) => setLabs(r.data || []));
  }, [clientId]);

  React.useEffect(() => {
    load();
    api.get("/labs/presets").then((r) => {
      setPresets(r.data.presets || []);
      if (r.data.presets?.[0] && !form.test_name) {
        applyPreset(r.data.presets[0]);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  const applyPreset = (p) => {
    setForm((f) => ({ ...f, test_name: p.test_name, unit: p.unit || "", reference_low: p.reference_low ?? "", reference_high: p.reference_high ?? "" }));
  };

  const save = async () => {
    if (!form.test_name || form.value === "") return toast({ title: "Pick a test and enter a value" });
    try {
      await api.post("/lab-values", {
        client_id: clientId,
        test_name: form.test_name,
        value: Number(form.value),
        unit: form.unit || null,
        reference_low: form.reference_low === "" ? null : Number(form.reference_low),
        reference_high: form.reference_high === "" ? null : Number(form.reference_high),
        measured_at: new Date(form.measured_at).toISOString(),
        notes: form.notes || null,
      });
      toast({ title: "Recorded" });
      setForm({ ...form, value: "", notes: "" });
      load();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this lab value?")) return;
    await api.delete(`/lab-values/${id}`);
    load();
  };

  const byTest = React.useMemo(() => {
    const g = {};
    for (const l of labs) {
      (g[l.test_name] = g[l.test_name] || []).push({
        id: l.id,
        date: new Date(l.measured_at).toLocaleDateString(),
        t: new Date(l.measured_at).getTime(),
        value: l.value,
        ref_low: l.reference_low,
        ref_high: l.reference_high,
        unit: l.unit,
      });
    }
    Object.values(g).forEach((arr) => arr.sort((a, b) => a.t - b.t));
    return g;
  }, [labs]);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf7ee] p-5">
        <div className="grid md:grid-cols-6 gap-3">
          <div className="md:col-span-2">
            <Label>Test</Label>
            <Select value={form.test_name} onValueChange={(v) => {
              const p = presets.find((x) => x.test_name === v);
              if (p) applyPreset(p); else setForm({ ...form, test_name: v });
            }}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
              <SelectContent>{presets.map((p) => <SelectItem key={p.test_name} value={p.test_name}>{p.test_name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div><Label>Value</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="number" step="any" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} /></div>
          <div><Label>Unit</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} /></div>
          <div><Label>Ref low</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="number" step="any" value={form.reference_low} onChange={(e) => setForm({ ...form, reference_low: e.target.value })} /></div>
          <div><Label>Ref high</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="number" step="any" value={form.reference_high} onChange={(e) => setForm({ ...form, reference_high: e.target.value })} /></div>
          <div><Label>Measured</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="date" value={form.measured_at} onChange={(e) => setForm({ ...form, measured_at: e.target.value })} /></div>
          <div className="md:col-span-5"><Label>Notes</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] min-h-[60px]" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
        </div>
        <div className="flex justify-end mt-3">
          <Button onClick={save} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"><Plus size={14} className="mr-2" /> Record value</Button>
        </div>
      </div>

      {Object.keys(byTest).length === 0 ? (
        <div className="text-sm text-[#6a6a6a]">No lab values recorded yet.</div>
      ) : (
        Object.entries(byTest).map(([name, data]) => {
          const latest = data[data.length - 1];
          const out = latest.ref_low != null && latest.ref_high != null && (latest.value < latest.ref_low || latest.value > latest.ref_high);
          return (
            <div key={name} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="font-display text-xl text-[#1f2a22]">{name}</div>
                  <div className="text-xs text-[#6a6a6a]">Latest: <span className={out ? "text-[#7a2a2a] font-semibold" : "text-[#2f4a3a] font-semibold"}>{latest.value}</span> {latest.unit || ""} on {latest.date}</div>
                </div>
              </div>
              <div style={{ width: "100%", height: 180 }}>
                <ResponsiveContainer>
                  <LineChart data={data} margin={{ top: 10, right: 16, bottom: 10, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e7dfc9" />
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6a6a6a" }} />
                    <YAxis tick={{ fontSize: 11, fill: "#6a6a6a" }} />
                    {latest.ref_low != null && latest.ref_high != null && (
                      <ReferenceArea y1={latest.ref_low} y2={latest.ref_high} fill="#c19a4b" fillOpacity={0.12} />
                    )}
                    <Tooltip contentStyle={{ background: "#fbf7ee", border: "1px solid #e7dfc9", borderRadius: 8, fontSize: 12 }} />
                    <Line type="monotone" dataKey="value" stroke="#2f4a3a" strokeWidth={2} dot={{ r: 4, fill: "#c19a4b" }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 text-xs">
                {data.map((d) => (
                  <span key={d.id} className="inline-flex items-center gap-1 mr-3 text-[#6a6a6a]">
                    {d.date}: <b className="text-[#1f2a22]">{d.value}</b>
                    <button onClick={() => remove(d.id)} className="text-[#7a2a2a] hover:opacity-70" title="Delete"><Trash2 size={10} /></button>
                  </span>
                ))}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}