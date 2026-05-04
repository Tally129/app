import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { CalendarDays, Plus, X } from "lucide-react";

export default function PatientAppointments() {
  const { toast } = useToast();
  const [items, setItems] = React.useState([]);
  const [open, setOpen] = React.useState(false);
  const [practitioners, setPractitioners] = React.useState([]);
  const [form, setForm] = React.useState({ practitioner_id: "", date: "", slot: "" });
  const [slots, setSlots] = React.useState([]);

  const load = () => api.get("/appointments").then((r) => setItems(r.data || []));
  React.useEffect(() => {
    load();
    api.get("/practitioners").then((r) => {
      setPractitioners(r.data || []);
      if (r.data?.[0]) setForm((f) => ({ ...f, practitioner_id: r.data[0].id }));
    });
  }, []);

  const loadSlots = React.useCallback(async () => {
    if (!form.practitioner_id || !form.date) return setSlots([]);
    const r = await api.get("/availability/slots", {
      params: { practitioner_id: form.practitioner_id, date: form.date, duration_min: 60 },
    });
    setSlots(r.data.slots || []);
  }, [form.practitioner_id, form.date]);

  React.useEffect(() => { loadSlots(); }, [loadSlots]);

  const book = async () => {
    if (!form.slot) return toast({ title: "Pick a time slot" });
    const s = slots.find((x) => x.start === form.slot);
    if (!s) return;
    try {
      const me = await api.get("/clients/me");
      await api.post("/appointments", {
        client_id: me.data.id,
        practitioner_id: form.practitioner_id,
        service: "Consultation",
        start: s.start,
        end: s.end,
        status: "requested",
      });
      toast({ title: "Requested", description: "We’ll confirm your appointment shortly." });
      setOpen(false);
      load();
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
  };

  const cancel = async (a) => {
    if (!window.confirm("Cancel this appointment?")) return;
    await api.put(`/appointments/${a.id}`, { status: "canceled" });
    load();
  };

  const upcoming = items.filter((a) => new Date(a.start) >= new Date() && a.status !== "canceled");
  const past = items.filter((a) => new Date(a.start) < new Date() || a.status === "canceled");

  return (
    <PortalLayout>
      <PortalHeader
        title="Appointments"
        subtitle="Book or manage your visits"
        actions={<Button onClick={() => setOpen(true)} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"><Plus size={16} className="mr-2" /> Book visit</Button>}
      />

      <h2 className="eyebrow text-[#8a6a3c] mb-3">Upcoming</h2>
      {upcoming.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <CalendarDays size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No upcoming appointments.</div>
        </div>
      ) : (
        <ul className="space-y-3">
          {upcoming.map((a) => (
            <li key={a.id} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 flex items-center justify-between">
              <div>
                <div className="font-display text-lg text-[#1f2a22]">{new Date(a.start).toLocaleString([], { weekday: "long", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</div>
                <div className="text-sm text-[#6a6a6a]">{a.service || "Consultation"} · with {a.practitioner_name || "Practitioner"}</div>
                <div className="text-xs text-[#8a6a3c] uppercase tracking-widest mt-1">{a.status}</div>
              </div>
              <Button size="sm" variant="outline" onClick={() => cancel(a)} className="rounded-full border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#7a2a2a] hover:text-[#f6f1e6]"><X size={14} className="mr-1" /> Cancel</Button>
            </li>
          ))}
        </ul>
      )}

      <h2 className="eyebrow text-[#8a6a3c] mt-10 mb-3">Past & canceled</h2>
      {past.length === 0 ? (
        <div className="text-sm text-[#6a6a6a]">No past appointments.</div>
      ) : (
        <ul className="space-y-2">
          {past.map((a) => (
            <li key={a.id} className="rounded-xl border border-[#e7dfc9] bg-[#fbf7ee] p-4 text-sm flex items-center justify-between">
              <span>{new Date(a.start).toLocaleDateString()} · {a.service || "—"} · {a.practitioner_name || "—"}</span>
              <span className="uppercase text-[10px] tracking-widest text-[#8a6a3c]">{a.status}</span>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader><DialogTitle className="font-display text-2xl">Book a visit</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Practitioner</Label>
              <Select value={form.practitioner_id} onValueChange={(v) => setForm({ ...form, practitioner_id: v, slot: "" })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
                <SelectContent>{practitioners.map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Date</Label>
              <input type="date" min={new Date().toISOString().slice(0,10)} value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value, slot: "" })} className="mt-2 h-10 w-full rounded-md bg-[#f6f1e6] border border-[#e0d6bc] px-3 text-sm" />
            </div>
            {form.date && (
              <div>
                <Label>Available times</Label>
                {slots.length === 0 ? (
                  <div className="text-xs text-[#6a6a6a] mt-2">No open slots on this date.</div>
                ) : (
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    {slots.map((s) => (
                      <button
                        key={s.start}
                        onClick={() => setForm({ ...form, slot: s.start })}
                        className={`rounded-full px-3 py-2 text-xs border ${form.slot === s.start ? "bg-[#2f4a3a] text-[#f6f1e6] border-[#2f4a3a]" : "bg-[#fbf7ee] text-[#3a3a3a] border-[#e0d6bc] hover:border-[#c19a4b]"}`}
                      >
                        {new Date(s.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={book} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">Request visit</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
