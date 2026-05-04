import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { ChevronLeft, ChevronRight, CalendarDays, Plus, Trash2 } from "lucide-react";

const HOUR_START = 8;
const HOUR_END = 19;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function startOfWeek(d) {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Mon=0
  x.setDate(x.getDate() - day);
  x.setHours(0, 0, 0, 0);
  return x;
}
function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function fmtISODate(d) { return d.toISOString().slice(0, 10); }
function sameDay(a, b) { return a.toDateString() === b.toDateString(); }

const STATUS_COLORS = {
  requested: { bg: "#fbf2d9", border: "#c19a4b", text: "#6b4a1c" },
  confirmed: { bg: "#2f4a3a", border: "#2f4a3a", text: "#f6f1e6" },
  completed: { bg: "#e7dfc9", border: "#8a6a3c", text: "#3a3a3a" },
  canceled:  { bg: "#f1ead8", border: "#7a2a2a", text: "#7a2a2a" },
  no_show:   { bg: "#f1ead8", border: "#7a2a2a", text: "#7a2a2a" },
};

export default function ProviderSchedule() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [weekStart, setWeekStart] = React.useState(() => startOfWeek(new Date()));
  const [appts, setAppts] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [openNew, setOpenNew] = React.useState(false);
  const [editing, setEditing] = React.useState(null);
  const [newSlot, setNewSlot] = React.useState(null); // {date, time}
  const [form, setForm] = React.useState({ client_id: "", service: "", duration: 60, notes: "", status: "confirmed" });

  const weekEnd = React.useMemo(() => addDays(weekStart, 7), [weekStart]);

  const load = React.useCallback(async () => {
    const r = await api.get("/appointments", {
      params: {
        start: weekStart.toISOString(),
        end: weekEnd.toISOString(),
        practitioner_id: user?.id,
      },
    });
    setAppts(r.data || []);
  }, [weekStart, weekEnd, user?.id]);

  React.useEffect(() => { load(); }, [load]);
  React.useEffect(() => { api.get("/clients").then((r) => setClients(r.data || [])); }, []);

  const openCreate = (date, hour) => {
    const d = new Date(date); d.setHours(hour, 0, 0, 0);
    setNewSlot({ date: d });
    setForm({ client_id: clients[0]?.id || "", service: "Consultation", duration: 60, notes: "", status: "confirmed" });
    setOpenNew(true);
  };

  const createAppt = async () => {
    if (!form.client_id || !newSlot) return toast({ title: "Pick a client and slot" });
    const start = new Date(newSlot.date);
    const end = new Date(start.getTime() + form.duration * 60000);
    try {
      await api.post("/appointments", {
        client_id: form.client_id,
        practitioner_id: user.id,
        service: form.service,
        notes: form.notes,
        status: form.status,
        start: start.toISOString(),
        end: end.toISOString(),
      });
      toast({ title: "Appointment created" });
      setOpenNew(false);
      load();
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
  };

  const updateAppt = async (changes) => {
    try {
      await api.put(`/appointments/${editing.id}`, changes);
      toast({ title: "Updated" });
      setEditing(null);
      load();
    } catch (e) { toast({ title: "Failed" }); }
  };

  const onDragStart = (e, a) => { e.dataTransfer.setData("apptId", a.id); e.dataTransfer.setData("apptDuration", String((new Date(a.end) - new Date(a.start)) / 60000)); };
  const onDropSlot = async (e, day, hour) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("apptId");
    const dur = Number(e.dataTransfer.getData("apptDuration")) || 60;
    if (!id) return;
    const start = new Date(day); start.setHours(hour, 0, 0, 0);
    const end = new Date(start.getTime() + dur * 60000);
    try {
      await api.put(`/appointments/${id}`, { start: start.toISOString(), end: end.toISOString() });
      toast({ title: "Rescheduled" });
      load();
    } catch { toast({ title: "Reschedule failed" }); }
  };

  const hours = Array.from({ length: HOUR_END - HOUR_START }, (_, i) => HOUR_START + i);
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));

  const apptsFor = (day, hour) =>
    appts.filter((a) => {
      const s = new Date(a.start);
      return sameDay(s, day) && s.getHours() === hour;
    });

  return (
    <PortalLayout>
      <PortalHeader
        title="Schedule"
        subtitle="Weekly calendar — drag a card to reschedule, click a slot to book."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setWeekStart(addDays(weekStart, -7))} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6]"><ChevronLeft size={16} /></Button>
            <Button variant="outline" onClick={() => setWeekStart(startOfWeek(new Date()))} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6]"><CalendarDays size={14} className="mr-1" /> Today</Button>
            <Button variant="outline" onClick={() => setWeekStart(addDays(weekStart, 7))} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6]"><ChevronRight size={16} /></Button>
          </div>
        }
      />

      <div className="text-sm text-[#6a6a6a] mb-3">
        Week of {weekStart.toLocaleDateString()} — {addDays(weekStart, 6).toLocaleDateString()}
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-auto">
        <div className="min-w-[900px] grid" style={{ gridTemplateColumns: "60px repeat(7, 1fr)" }}>
          <div className="border-b border-[#e7dfc9] py-2 bg-[#f1ead8]"></div>
          {days.map((d, i) => (
            <div key={i} className={`text-center py-2 border-b border-[#e7dfc9] ${sameDay(d, new Date()) ? "bg-[#e7dfc9]" : "bg-[#f1ead8]"}`}>
              <div className="eyebrow text-[#8a6a3c]">{DAYS[i]}</div>
              <div className="text-sm font-medium">{d.getDate()}</div>
            </div>
          ))}
          {hours.map((h) => (
            <React.Fragment key={h}>
              <div className="border-b border-r border-[#e7dfc9] text-[11px] text-[#8a8a8a] text-right pr-2 py-3">{h}:00</div>
              {days.map((d, i) => {
                const cell = apptsFor(d, h);
                return (
                  <div
                    key={i}
                    onClick={() => cell.length === 0 && openCreate(d, h)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => onDropSlot(e, d, h)}
                    className={`relative border-b border-r border-[#e7dfc9] min-h-[58px] ${cell.length === 0 ? "hover:bg-[#f1ead8]/50 cursor-pointer" : ""}`}
                  >
                    {cell.map((a) => {
                      const col = STATUS_COLORS[a.status] || STATUS_COLORS.confirmed;
                      return (
                        <div
                          key={a.id}
                          draggable
                          onDragStart={(e) => onDragStart(e, a)}
                          onClick={(e) => { e.stopPropagation(); setEditing(a); }}
                          className="m-1 rounded-md border px-2 py-1 text-[11px] leading-tight cursor-move"
                          style={{ background: col.bg, borderColor: col.border, color: col.text }}
                          title={`${a.client_name} — ${a.status}`}
                        >
                          <div className="font-medium truncate">{a.client_name || "—"}</div>
                          <div className="truncate opacity-80">{new Date(a.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · {a.service || "Visit"}</div>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Create Dialog */}
      <Dialog open={openNew} onOpenChange={setOpenNew}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader><DialogTitle className="font-display text-2xl">New appointment</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-[#6a6a6a]">{newSlot?.date?.toLocaleString()}</div>
            <div><Label>Client</Label>
              <Select value={form.client_id} onValueChange={(v) => setForm({ ...form, client_id: v })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue placeholder="Select client" /></SelectTrigger>
                <SelectContent>{clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Service</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.service} onChange={(e) => setForm({ ...form, service: e.target.value })} /></div>
              <div><Label>Duration (min)</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="number" value={form.duration} onChange={(e) => setForm({ ...form, duration: Number(e.target.value) || 60 })} /></div>
            </div>
            <div><Label>Notes</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpenNew(false)}>Cancel</Button>
            <Button onClick={createAppt} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editing} onOpenChange={() => setEditing(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader><DialogTitle className="font-display text-2xl">Appointment</DialogTitle></DialogHeader>
          {editing && (
            <div className="space-y-3 text-sm">
              <div><span className="text-[#6a6a6a]">Client:</span> {editing.client_name}</div>
              <div><span className="text-[#6a6a6a]">When:</span> {new Date(editing.start).toLocaleString()}</div>
              <div><span className="text-[#6a6a6a]">Service:</span> {editing.service || "—"}</div>
              <div><Label>Status</Label>
                <Select value={editing.status} onValueChange={(v) => updateAppt({ status: v })}>
                  <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {["requested","confirmed","completed","canceled","no_show"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
