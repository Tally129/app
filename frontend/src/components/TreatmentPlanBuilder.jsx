import React from "react";
import api from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Checkbox } from "./ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "./ui/dialog";
import { useToast } from "../hooks/use-toast";
import { Plus, Pill, Apple, Moon, TestTube2, CalendarCheck, Eye, EyeOff, Trash2 } from "lucide-react";

const TYPE_META = {
  supplement: { icon: Pill, label: "Supplement" },
  diet: { icon: Apple, label: "Diet" },
  lifestyle: { icon: Moon, label: "Lifestyle" },
  lab_order: { icon: TestTube2, label: "Lab order" },
  follow_up: { icon: CalendarCheck, label: "Follow-up" },
};

export default function TreatmentPlanBuilder({ clientId, onClose }) {
  const { toast } = useToast();
  const [plans, setPlans] = React.useState([]);
  const [editing, setEditing] = React.useState(null); // plan doc being edited
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const load = React.useCallback(() => {
    api.get("/treatment-plans", { params: { client_id: clientId } }).then((r) => setPlans(r.data || []));
  }, [clientId]);

  React.useEffect(() => { load(); }, [load]);

  const startNew = () => {
    setEditing({
      client_id: clientId,
      title: "New treatment plan",
      status: "active",
      follow_up_days: 7,
      items: [],
    });
    setDialogOpen(true);
  };

  const edit = (p) => { setEditing({ ...p }); setDialogOpen(true); };

  const setItem = (idx, key, val) => {
    const items = [...editing.items];
    items[idx] = { ...items[idx], [key]: val };
    setEditing({ ...editing, items });
  };
  const addItem = (type) => {
    setEditing({
      ...editing,
      items: [...editing.items, { type, title: "", detail: "", dose: "", frequency: "", duration: "", patient_visible: true }],
    });
  };
  const removeItem = (idx) => setEditing({ ...editing, items: editing.items.filter((_, i) => i !== idx) });

  const save = async () => {
    try {
      if (editing.id) {
        await api.put(`/treatment-plans/${editing.id}`, editing);
      } else {
        await api.post("/treatment-plans", editing);
      }
      toast({ title: "Plan saved" });
      setDialogOpen(false);
      setEditing(null);
      load();
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={startNew} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"><Plus size={16} className="mr-2" /> New plan</Button>
      </div>

      {plans.length === 0 && <div className="text-[#6a6a6a] text-sm">No treatment plans yet.</div>}

      {plans.map((p) => (
        <div key={p.id} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-display text-xl text-[#1f2a22]">{p.title}</div>
              <div className="text-xs text-[#6a6a6a] mt-1">
                {p.status} · {new Date(p.created_at).toLocaleDateString()} · by {p.practitioner_name || "—"}
              </div>
            </div>
            <Button variant="outline" onClick={() => edit(p)} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#2f4a3a] hover:text-[#f6f1e6]">Edit</Button>
          </div>
          <ul className="mt-4 space-y-2">
            {p.items.map((it, i) => {
              const M = TYPE_META[it.type] || TYPE_META.lifestyle;
              const Icon = M.icon;
              return (
                <li key={i} className="flex items-start gap-3 text-sm">
                  <Icon size={16} className="mt-0.5 text-[#2f4a3a]" />
                  <div className="flex-1">
                    <div className="font-medium text-[#1f2a22]">{it.title} <span className="text-[11px] tracking-widest uppercase text-[#8a6a3c] ml-2">{M.label}</span></div>
                    <div className="text-[#5a5a5a]">{[it.dose, it.frequency, it.duration].filter(Boolean).join(" · ")}</div>
                    {it.detail && <div className="text-[#6a6a6a] text-xs mt-0.5">{it.detail}</div>}
                  </div>
                  {it.patient_visible ? <Eye size={14} className="text-[#2f4a3a] mt-0.5" /> : <EyeOff size={14} className="text-[#8a6a3c] mt-0.5" />}
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      {/* Editor */}
      <Dialog open={dialogOpen} onOpenChange={(o) => { if (!o) { setDialogOpen(false); setEditing(null); } }}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display text-2xl">{editing?.id ? "Edit plan" : "New treatment plan"}</DialogTitle></DialogHeader>
          {editing && (
            <div className="space-y-4">
              <div className="grid md:grid-cols-3 gap-3">
                <div className="md:col-span-2"><Label>Title</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} /></div>
                <div><Label>Follow-up (days)</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="number" value={editing.follow_up_days || ""} onChange={(e) => setEditing({ ...editing, follow_up_days: Number(e.target.value) || null })} /></div>
              </div>
              <div><Label>Status</Label>
                <Select value={editing.status} onValueChange={(v) => setEditing({ ...editing, status: v })}>
                  <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>{["draft","active","completed"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                </Select>
              </div>

              <div className="flex flex-wrap gap-2">
                {Object.entries(TYPE_META).map(([k, m]) => (
                  <Button key={k} size="sm" variant="outline" onClick={() => addItem(k)} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#2f4a3a] hover:text-[#f6f1e6]">
                    <m.icon size={14} className="mr-1" /> Add {m.label}
                  </Button>
                ))}
              </div>

              <div className="space-y-3">
                {editing.items.length === 0 && <div className="text-[#6a6a6a] text-sm">Add items above.</div>}
                {editing.items.map((it, i) => {
                  const M = TYPE_META[it.type] || TYPE_META.lifestyle;
                  return (
                    <div key={i} className="rounded-xl border border-[#e0d6bc] bg-[#f6f1e6] p-4 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="text-[11px] tracking-widest uppercase text-[#8a6a3c] flex items-center gap-2">
                          <M.icon size={14} /> {M.label}
                        </div>
                        <div className="flex items-center gap-3">
                          <label className="text-xs flex items-center gap-2 cursor-pointer">
                            <Checkbox checked={it.patient_visible} onCheckedChange={(c) => setItem(i, "patient_visible", !!c)} />
                            Patient-visible
                          </label>
                          <Button size="sm" variant="outline" onClick={() => removeItem(i)} className="rounded-full border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#7a2a2a] hover:text-[#f6f1e6]"><Trash2 size={12} /></Button>
                        </div>
                      </div>
                      <Input placeholder="Title (e.g. Magnesium glycinate)" className="bg-[#fbf7ee] border-[#e0d6bc]" value={it.title} onChange={(e) => setItem(i, "title", e.target.value)} />
                      {(it.type === "supplement" || it.type === "lab_order") && (
                        <div className="grid grid-cols-3 gap-2">
                          <Input placeholder="Dose" className="bg-[#fbf7ee] border-[#e0d6bc]" value={it.dose || ""} onChange={(e) => setItem(i, "dose", e.target.value)} />
                          <Input placeholder="Frequency" className="bg-[#fbf7ee] border-[#e0d6bc]" value={it.frequency || ""} onChange={(e) => setItem(i, "frequency", e.target.value)} />
                          <Input placeholder="Duration" className="bg-[#fbf7ee] border-[#e0d6bc]" value={it.duration || ""} onChange={(e) => setItem(i, "duration", e.target.value)} />
                        </div>
                      )}
                      <Textarea placeholder="Notes / detail" className="bg-[#fbf7ee] border-[#e0d6bc] min-h-[60px]" value={it.detail || ""} onChange={(e) => setItem(i, "detail", e.target.value)} />
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setDialogOpen(false); setEditing(null); }}>Cancel</Button>
            <Button onClick={save} className="bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">Save plan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
