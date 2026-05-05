import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { useToast } from "../../hooks/use-toast";
import {
  ChevronLeft, ChevronRight, Plus, CalendarDays, Video, Building2,
  PhoneCall, CheckCircle2, XCircle, UserCheck, PlayCircle, ExternalLink,
} from "lucide-react";

// ----------- Date helpers -----------
const startOfWeek = (d) => {
  const x = new Date(d); const day = x.getDay() || 7;
  if (day !== 1) x.setHours(-24 * (day - 1));
  x.setHours(0, 0, 0, 0); return x;
};
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const dateKey = (d) => d.toISOString().slice(0, 10);

const STATUS = {
  scheduled:   { label: "Scheduled",   color: "#8a6a3c", bg: "#fbeed4" },
  arrived:     { label: "Arrived",     color: "#2f4a3a", bg: "#dceadb" },
  in_session:  { label: "In session",  color: "#1f2a22", bg: "#c19a4b" },
  completed:   { label: "Completed",   color: "#5b6f5b", bg: "#eaeadf" },
  no_show:     { label: "No-show",     color: "#7a2a2a", bg: "#f3d7d7" },
  cancelled:   { label: "Cancelled",   color: "#7a7a7a", bg: "#ececec" },
};

const HOURS = Array.from({ length: 12 }, (_, i) => 8 + i); // 8 AM – 7 PM

// ----------- main page -----------
export default function AppointmentsEHR() {
  const { toast } = useToast();
  const [view, setView] = React.useState("week"); // day | week
  const [anchor, setAnchor] = React.useState(new Date());
  const [appts, setAppts] = React.useState([]);
  const [practitioners, setPractitioners] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [treatments, setTreatments] = React.useState([]);
  const [selected, setSelected] = React.useState(null); // appointment for drawer
  const [creatingFor, setCreatingFor] = React.useState(null); // {date, hour}

  const load = React.useCallback(async () => {
    try {
      const [a, p, c, t] = await Promise.all([
        api.get("/appointments"),
        api.get("/practitioners"),
        api.get("/clients"),
        api.get("/treatments?active_only=true").catch(() => ({ data: [] })),
      ]);
      setAppts(a.data || []);
      setPractitioners(p.data || []);
      setClients(c.data || []);
      setTreatments(t.data || []);
    } catch (e) {
      toast({ title: "Failed to load schedule", description: e?.response?.data?.detail || "" });
    }
  }, [toast]);

  React.useEffect(() => { load(); }, [load]);

  const days = view === "week"
    ? Array.from({ length: 7 }, (_, i) => addDays(startOfWeek(anchor), i))
    : [new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())];

  const apptsByDayHour = React.useMemo(() => {
    const map = {};
    for (const a of appts) {
      if (!a.start) continue;
      const d = new Date(a.start);
      const k = dateKey(d);
      const h = d.getHours();
      map[k] = map[k] || {}; map[k][h] = map[k][h] || []; map[k][h].push(a);
    }
    return map;
  }, [appts]);

  const today = new Date(); today.setHours(0, 0, 0, 0);
  const todayUpcoming = appts
    .filter((a) => a.start && new Date(a.start) >= today)
    .sort((a, b) => new Date(a.start) - new Date(b.start))
    .slice(0, 4);

  const updateStatus = async (id, status) => {
    try {
      await api.put(`/appointments/${id}`, { status });
      toast({ title: `Marked ${STATUS[status]?.label || status}` });
      load(); setSelected(null);
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Appointments"
        subtitle={view === "week"
          ? `${days[0].toLocaleDateString([], { month: "short", day: "numeric" })} – ${days[6].toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}`
          : days[0].toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
        actions={
          <div className="flex gap-2 items-center">
            <div className="flex items-center gap-1">
              <Button variant="outline" size="sm" className="h-9 w-9 p-0 rounded-full"
                onClick={() => setAnchor(addDays(anchor, view === "week" ? -7 : -1))}
                data-testid="appts-prev-btn"><ChevronLeft size={14} /></Button>
              <Button variant="outline" size="sm" className="h-9 rounded-full px-3" onClick={() => setAnchor(new Date())} data-testid="appts-today-btn">Today</Button>
              <Button variant="outline" size="sm" className="h-9 w-9 p-0 rounded-full"
                onClick={() => setAnchor(addDays(anchor, view === "week" ? 7 : 1))}
                data-testid="appts-next-btn"><ChevronRight size={14} /></Button>
            </div>
            <Select value={view} onValueChange={setView}>
              <SelectTrigger className="w-28 h-9 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="appts-view-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="day">Day</SelectItem>
                <SelectItem value="week">Week</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={() => setCreatingFor({ date: anchor, hour: 9 })} className="h-9 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="appts-new-btn">
              <Plus size={14} className="mr-1" /> New
            </Button>
          </div>
        }
      />

      {/* Today strip */}
      <div className="mb-6 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4" data-testid="appts-today-strip">
        <div className="eyebrow text-[#8a6a3c] mb-3">Up next</div>
        {todayUpcoming.length === 0 ? (
          <div className="text-sm text-[#6a6a6a]">No upcoming visits</div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {todayUpcoming.map((a) => {
              const st = STATUS[a.status] || STATUS.scheduled;
              return (
                <button key={a.id} onClick={() => setSelected(a)} className="text-left rounded-xl border border-[#e0d6bc] bg-[#f6f1e6] p-3 hover:bg-[#f1ead8]" data-testid={`appts-upnext-${a.id}`}>
                  <div className="text-xs uppercase tracking-wider" style={{ color: st.color }}>{st.label}</div>
                  <div className="text-sm font-medium text-[#1f2a22] truncate mt-0.5">{a.client_name || "—"}</div>
                  <div className="text-xs text-[#6a6a6a] mt-1 flex items-center gap-1">
                    {a.visit_mode === "telehealth" ? <Video size={11} /> : <Building2 size={11} />}
                    {new Date(a.start).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Calendar grid */}
      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
        <div className={`grid ${view === "week" ? "grid-cols-8" : "grid-cols-2"} border-b border-[#e7dfc9] bg-[#f1ead8] text-[10px] uppercase tracking-widest text-[#8a6a3c]`}>
          <div className="p-2" />
          {days.map((d) => (
            <div key={dateKey(d)} className={`p-3 text-center ${dateKey(d) === dateKey(new Date()) ? "text-[#2f4a3a] font-semibold" : ""}`}>
              {d.toLocaleDateString([], { weekday: "short" })}
              <div className="text-[14px] mt-0.5">{d.getDate()}</div>
            </div>
          ))}
        </div>
        <div className="overflow-y-auto max-h-[60vh]">
          {HOURS.map((h) => (
            <div key={h} className={`grid ${view === "week" ? "grid-cols-8" : "grid-cols-2"} border-b border-[#e7dfc9]/60`}>
              <div className="p-2 text-[11px] text-[#8a6a3c] text-right pr-3 border-r border-[#e7dfc9]">
                {h % 12 || 12}{h < 12 ? "a" : "p"}
              </div>
              {days.map((d) => {
                const k = dateKey(d);
                const cellAppts = (apptsByDayHour[k] && apptsByDayHour[k][h]) || [];
                return (
                  <button
                    key={`${k}-${h}`}
                    onClick={() => setCreatingFor({ date: d, hour: h })}
                    className="min-h-[48px] p-1 border-r border-[#e7dfc9]/60 text-left hover:bg-[#f1ead8]/40 relative group"
                    data-testid={`appts-cell-${k}-${h}`}
                  >
                    {cellAppts.map((a) => {
                      const st = STATUS[a.status] || STATUS.scheduled;
                      return (
                        <div
                          key={a.id}
                          onClick={(e) => { e.stopPropagation(); setSelected(a); }}
                          className="rounded px-1.5 py-1 mb-1 text-[10px] truncate cursor-pointer border-l-2"
                          style={{ background: st.bg, color: st.color, borderColor: st.color }}
                        >
                          {new Date(a.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · {a.client_name || "—"}
                        </div>
                      );
                    })}
                    <span className="opacity-0 group-hover:opacity-100 absolute top-1 right-1 text-[10px] text-[#8a6a3c]">+ Add</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Side drawer for selected appointment */}
      <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <SheetContent className="bg-[#fbf7ee] border-[#e7dfc9] sm:max-w-md w-full overflow-y-auto" data-testid="appt-drawer">
          {selected && (
            <>
              <SheetHeader>
                <SheetTitle className="font-display text-2xl">{selected.client_name || "Appointment"}</SheetTitle>
                <SheetDescription>
                  {new Date(selected.start).toLocaleString([], { dateStyle: "full", timeStyle: "short" })}
                </SheetDescription>
              </SheetHeader>
              <div className="mt-6 space-y-4">
                <KV k="MRN" v={(clients.find((c) => c.id === selected.client_id) || {}).mrn || "—"} />
                <KV k="Provider" v={selected.practitioner_name || "—"} />
                <KV k="Visit type" v={selected.visit_type || "Consultation"} />
                <KV k="Mode" v={selected.visit_mode === "telehealth" ? "Telehealth" : "In-clinic"} />
                <KV k="Status" v={
                  <span style={{ color: (STATUS[selected.status] || STATUS.scheduled).color }} className="font-medium">
                    {(STATUS[selected.status] || STATUS.scheduled).label}
                  </span>
                } />
                {selected.reason && <KV k="Reason" v={selected.reason} />}

                <div className="pt-4 border-t border-[#e7dfc9]">
                  <div className="eyebrow text-[#8a6a3c] mb-3">Workflow</div>
                  <div className="grid grid-cols-2 gap-2">
                    <ActionBtn icon={UserCheck} label="Mark arrived" disabled={selected.status === "arrived" || selected.status === "completed"}
                      onClick={() => updateStatus(selected.id, "arrived")} testid="appt-mark-arrived" />
                    <ActionBtn icon={PlayCircle} label="Start visit" disabled={selected.status === "completed"}
                      onClick={() => updateStatus(selected.id, "in_session")} testid="appt-start-visit" />
                    <ActionBtn icon={CheckCircle2} label="Complete" disabled={selected.status === "completed"}
                      onClick={() => updateStatus(selected.id, "completed")} testid="appt-complete" />
                    <ActionBtn icon={XCircle} label="No-show"
                      onClick={() => updateStatus(selected.id, "no_show")} testid="appt-no-show" />
                  </div>

                  {selected.visit_mode === "telehealth" && (
                    <Link to={`/portal/visit/${selected.id}`}
                      className="mt-3 inline-flex items-center gap-2 text-sm text-[#2f4a3a] hover:underline"
                      data-testid="appt-open-telehealth">
                      <Video size={14} /> Open telehealth room <ExternalLink size={11} />
                    </Link>
                  )}
                  <Link to={`/portal/provider/patients/${selected.client_id}`}
                    className="block mt-2 text-sm text-[#2f4a3a] hover:underline">
                    Open client chart →
                  </Link>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* New appointment dialog */}
      <NewAppointmentDialog
        open={!!creatingFor}
        onOpenChange={(o) => !o && setCreatingFor(null)}
        prefill={creatingFor}
        practitioners={practitioners}
        clients={clients}
        treatments={treatments}
        onCreated={() => { setCreatingFor(null); load(); }}
      />
    </PortalLayout>
  );
}

function KV({ k, v }) {
  return <div className="flex items-baseline justify-between text-sm"><span className="text-[#8a6a3c] uppercase text-[10px] tracking-wider">{k}</span><span className="text-[#1f2a22] text-right">{v}</span></div>;
}

function ActionBtn({ icon: Icon, label, onClick, disabled, testid }) {
  return (
    <Button onClick={onClick} disabled={disabled} variant="outline" size="sm"
      className="h-9 rounded-full text-xs border-[#2f4a3a] text-[#2f4a3a] disabled:opacity-40"
      data-testid={testid}>
      <Icon size={12} className="mr-1" /> {label}
    </Button>
  );
}

function NewAppointmentDialog({ open, onOpenChange, prefill, practitioners, clients, treatments, onCreated }) {
  const { toast } = useToast();
  const [form, setForm] = React.useState({
    client_id: "", practitioner_id: "", treatment_id: "__custom__", duration: 60,
    visit_mode: "in_clinic", reason: "", notes: "",
  });
  const [time, setTime] = React.useState(""); // HH:MM
  const [date, setDate] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (prefill?.date) {
      const d = prefill.date;
      setDate(d.toISOString().slice(0, 10));
      setTime(`${String(prefill.hour).padStart(2, "0")}:00`);
    }
  }, [prefill]);

  const submit = async () => {
    if (!form.client_id || !form.practitioner_id || !date || !time) {
      toast({ title: "Client, provider, date and time are required" });
      return;
    }
    setSubmitting(true);
    try {
      const start = new Date(`${date}T${time}:00`);
      const tx = treatments.find((t) => t.id === form.treatment_id);
      const dur = tx?.duration_min || parseInt(form.duration) || 60;
      const end = new Date(start.getTime() + dur * 60000);
      await api.post("/appointments", {
        client_id: form.client_id,
        practitioner_id: form.practitioner_id,
        start: start.toISOString(),
        end: end.toISOString(),
        visit_mode: form.visit_mode,
        visit_type: tx?.name || "Consultation",
        reason: form.reason,
        notes: form.notes,
      });
      toast({ title: "Appointment created" });
      onCreated();
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">New appointment</DialogTitle>
          <DialogDescription>Schedule an in-clinic or telehealth visit.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 max-h-[60vh] overflow-y-auto pr-1">
          <div>
            <Label>Client</Label>
            <Select value={form.client_id} onValueChange={(v) => setForm({ ...form, client_id: v })}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="newappt-client"><SelectValue placeholder="Select client…" /></SelectTrigger>
              <SelectContent>
                {clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email || c.id}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Provider</Label>
            <Select value={form.practitioner_id} onValueChange={(v) => setForm({ ...form, practitioner_id: v })}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="newappt-provider"><SelectValue placeholder="Select provider…" /></SelectTrigger>
              <SelectContent>
                {practitioners.map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Treatment template</Label>
            <Select value={form.treatment_id} onValueChange={(v) => setForm({ ...form, treatment_id: v })}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue placeholder="Optional template…" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__custom__">— Custom —</SelectItem>
                {treatments.map((t) => <SelectItem key={t.id} value={t.id}>{t.name} ({t.duration_min}m)</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div><Label>Date</Label>
              <Input type="date" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={date} onChange={(e) => setDate(e.target.value)} data-testid="newappt-date" />
            </div>
            <div><Label>Time</Label>
              <Input type="time" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={time} onChange={(e) => setTime(e.target.value)} data-testid="newappt-time" />
            </div>
            <div><Label>Duration (min)</Label>
              <Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.duration} onChange={(e) => setForm({ ...form, duration: e.target.value })} />
            </div>
          </div>
          <div>
            <Label>Mode</Label>
            <Select value={form.visit_mode} onValueChange={(v) => setForm({ ...form, visit_mode: v })}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="newappt-mode"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="in_person">In clinic</SelectItem>
                <SelectItem value="telehealth">Telehealth</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div><Label>Reason / chief concern</Label>
            <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={submitting} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="newappt-submit">
            {submitting ? "Saving…" : "Schedule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
