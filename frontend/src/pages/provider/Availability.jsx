import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { Trash2 } from "lucide-react";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export default function Availability() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [items, setItems] = React.useState([]);
  const [form, setForm] = React.useState({ weekday: "0", start_time: "09:00", end_time: "17:00" });

  const load = () => api.get("/availability").then((r) => setItems(r.data || []));
  React.useEffect(() => { load(); }, []);

  const add = async () => {
    try {
      await api.post("/availability", {
        weekday: Number(form.weekday),
        start_time: form.start_time,
        end_time: form.end_time,
        active: true,
      });
      toast({ title: "Added" });
      load();
    } catch (e) { toast({ title: "Failed" }); }
  };

  const remove = async (id) => { await api.delete(`/availability/${id}`); load(); };

  return (
    <PortalLayout>
      <PortalHeader title="Availability" subtitle="Set recurring weekly hours for patient booking." />

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 mb-5 grid md:grid-cols-4 gap-3">
        <div><Label>Day</Label>
          <Select value={form.weekday} onValueChange={(v) => setForm({ ...form, weekday: v })}>
            <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
            <SelectContent>{DAYS.map((d, i) => <SelectItem key={d} value={String(i)}>{d}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div><Label>Start</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="time" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} /></div>
        <div><Label>End</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="time" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} /></div>
        <div className="flex items-end"><Button onClick={add} className="w-full rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">Add window</Button></div>
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr><th className="text-left py-3 px-4">Day</th><th className="text-left py-3 px-4">Start</th><th className="text-left py-3 px-4">End</th><th></th></tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={4} className="py-8 text-center text-[#6a6a6a]">No availability set</td></tr>}
            {items.map((a) => (
              <tr key={a.id} className="border-t border-[#e7dfc9]">
                <td className="py-3 px-4">{DAYS[a.weekday]}</td>
                <td className="py-3 px-4">{a.start_time}</td>
                <td className="py-3 px-4">{a.end_time}</td>
                <td className="py-3 px-4 text-right">
                  <Button size="sm" variant="outline" onClick={() => remove(a.id)} className="rounded-full border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#7a2a2a] hover:text-[#f6f1e6]"><Trash2 size={14} /></Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}
