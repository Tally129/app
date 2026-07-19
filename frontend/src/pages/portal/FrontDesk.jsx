import React from "react";
import { useSearchParams } from "react-router-dom";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { useToast } from "../../hooks/use-toast";
import { UserPlus, LogIn, LogOut, Building2, Users, Clock, X } from "lucide-react";
import { getErrorMessage } from "../../lib/errors";

const STATUSES = [
  { v: "checked_in", label: "Checked in" },
  { v: "in_room", label: "In room" },
  { v: "checked_out", label: "Checked out" },
  { v: "no_show", label: "No-show" },
];

export default function FrontDesk() {
  const { toast } = useToast();
  const [visits, setVisits] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [showCheckin, setShowCheckin] = React.useState(false);
  const [form, setForm] = React.useState({ client_id: "", room: "", walk_in: false });
  const [search, setSearch] = React.useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const filterKey = searchParams.get("filter") || "all"; // all | in_clinic | walk_in | checked_out

  const load = async () => {
    setLoading(true);
    try {
      const [v, c] = await Promise.all([
        api.get("/front-desk/today"),
        api.get("/clients"),
      ]);
      setVisits(v.data || []);
      setClients(c.data || []);
    } catch (e) {
      toast({ title: "Failed to load", description: getErrorMessage(e) || "" });
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);

  const checkIn = async () => {
    if (!form.client_id) {
      toast({ title: "Select a client" });
      return;
    }
    try {
      await api.post("/front-desk/check-in", form);
      toast({ title: "Checked in" });
      setShowCheckin(false);
      setForm({ client_id: "", room: "", walk_in: false });
      load();
    } catch (e) {
      toast({ title: "Failed", description: getErrorMessage(e) || "" });
    }
  };

  const updateVisit = async (id, payload) => {
    try {
      await api.put(`/front-desk/${id}`, payload);
      load();
    } catch (e) {
      toast({ title: "Failed", description: getErrorMessage(e) || "" });
    }
  };

  const filtered = visits.filter((v) => {
    if (search && !(v.client_name || "").toLowerCase().includes(search.toLowerCase())) return false;
    if (filterKey === "in_clinic") return v.status === "checked_in" || v.status === "in_room";
    if (filterKey === "walk_in") return v.walk_in;
    if (filterKey === "checked_out") return v.status === "checked_out";
    return true;
  });

  const setFilter = (key) => {
    const next = new URLSearchParams(searchParams);
    if (!key || key === filterKey || key === "all") next.delete("filter");
    else next.set("filter", key);
    setSearchParams(next);
  };

  const counts = {
    in: visits.filter((v) => v.status === "checked_in" || v.status === "in_room").length,
    walk: visits.filter((v) => v.walk_in).length,
    out: visits.filter((v) => v.status === "checked_out").length,
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Front Desk"
        subtitle="Today's queue · check-ins · room assignments"
        actions={
          <Button
            onClick={() => setShowCheckin(true)}
            className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
            data-testid="frontdesk-checkin-btn"
          >
            <UserPlus size={16} className="mr-2" /> Check in / Walk-in
          </Button>
        }
      />

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <button
          type="button"
          onClick={() => setFilter("in_clinic")}
          className={`text-left rounded-2xl transition ${filterKey === "in_clinic" ? "ring-2 ring-[#2f4a3a]" : "hover:-translate-y-0.5"}`}
          data-testid="fd-kpi-in-clinic"
        >
          <StatCard label="In clinic" value={counts.in} icon={Users} accent={filterKey === "in_clinic" ? "text-[#2f4a3a]" : undefined} />
        </button>
        <button
          type="button"
          onClick={() => setFilter("walk_in")}
          className={`text-left rounded-2xl transition ${filterKey === "walk_in" ? "ring-2 ring-[#c19a4b]" : "hover:-translate-y-0.5"}`}
          data-testid="fd-kpi-walk-ins"
        >
          <StatCard label="Walk-ins" value={counts.walk} icon={Building2} accent={filterKey === "walk_in" ? "text-[#8a6a3c]" : undefined} />
        </button>
        <button
          type="button"
          onClick={() => setFilter("checked_out")}
          className={`text-left rounded-2xl transition ${filterKey === "checked_out" ? "ring-2 ring-[#5b6f5b]" : "hover:-translate-y-0.5"}`}
          data-testid="fd-kpi-completed"
        >
          <StatCard label="Completed" value={counts.out} icon={Clock} accent={filterKey === "checked_out" ? "text-[#5b6f5b]" : undefined} />
        </button>
      </div>
      {filterKey !== "all" && (
        <div className="mb-4 flex items-center gap-2 text-xs text-[#8a6a3c]">
          <span>Filtered by</span>
          <span className="px-2 py-0.5 rounded-full bg-[#f1ead8] border border-[#e0d6bc] uppercase tracking-wider text-[10px]">
            {filterKey.replace("_", " ")}
          </span>
          <button onClick={() => setFilter("all")} className="inline-flex items-center gap-1 hover:underline" data-testid="fd-filter-clear">
            <X size={11} /> Clear
          </button>
        </div>
      )}

      <Input
        placeholder="Search by client name…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="mb-4 max-w-sm bg-[#f6f1e6] border-[#e0d6bc]"
        data-testid="frontdesk-search-input"
      />

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="frontdesk-table">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Client</th>
              <th className="text-left py-3 px-4">Status</th>
              <th className="text-left py-3 px-4">Room</th>
              <th className="text-left py-3 px-4">Type</th>
              <th className="text-left py-3 px-4">Check-in</th>
              <th className="text-left py-3 px-4">Check-out</th>
              <th className="text-right py-3 px-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={7} className="py-10 text-center text-[#6a6a6a]">No visits today.</td></tr>
            )}
            {filtered.map((v) => (
              <tr key={v.id} className="border-t border-[#e7dfc9]" data-testid={`fd-row-${v.id}`}>
                <td className="py-3 px-4 font-medium text-[#1f2a22]">{v.client_name || v.client_id}</td>
                <td className="py-3 px-4">
                  <Select value={v.status} onValueChange={(val) => updateVisit(v.id, { status: val })}>
                    <SelectTrigger className="h-8 w-36 bg-[#f6f1e6] border-[#e0d6bc] text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>{STATUSES.map((s) => <SelectItem key={s.v} value={s.v}>{s.label}</SelectItem>)}</SelectContent>
                  </Select>
                </td>
                <td className="py-3 px-4">
                  <Input
                    className="h-8 w-24 bg-[#f6f1e6] border-[#e0d6bc] text-xs"
                    defaultValue={v.room || ""}
                    onBlur={(e) => e.target.value !== (v.room || "") && updateVisit(v.id, { room: e.target.value || null })}
                    placeholder="—"
                    data-testid={`fd-room-input-${v.id}`}
                  />
                </td>
                <td className="py-3 px-4 text-xs">
                  {v.walk_in ? (
                    <span className="inline-block px-2 py-0.5 rounded-full bg-[#c19a4b] text-[#1f2a22]">Walk-in</span>
                  ) : (
                    <span className="text-[#6a6a6a]">Scheduled</span>
                  )}
                </td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">
                  {v.checked_in_at ? new Date(v.checked_in_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                </td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">
                  {v.checked_out_at ? new Date(v.checked_out_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                </td>
                <td className="py-3 px-4 text-right">
                  {v.status !== "checked_out" && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 rounded-full text-xs border-[#2f4a3a] text-[#2f4a3a]"
                      onClick={() => updateVisit(v.id, { status: "checked_out" })}
                      data-testid={`fd-checkout-btn-${v.id}`}
                    >
                      <LogOut size={12} className="mr-1" /> Check out
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={showCheckin} onOpenChange={setShowCheckin}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle>Check in client</DialogTitle>
            <DialogDescription>Record a scheduled or walk-in visit and assign a room.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Client</Label>
              <Select value={form.client_id} onValueChange={(v) => setForm({ ...form, client_id: v })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="checkin-client-select">
                  <SelectValue placeholder="Select client…" />
                </SelectTrigger>
                <SelectContent>
                  {clients.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.full_name || c.email || c.id}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Room (optional)</Label>
              <Input
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                value={form.room}
                onChange={(e) => setForm({ ...form, room: e.target.value })}
                placeholder="e.g. Room 2"
                data-testid="checkin-room-input"
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.walk_in}
                onChange={(e) => setForm({ ...form, walk_in: e.target.checked })}
                data-testid="checkin-walkin-cb"
              />
              Walk-in (no scheduled appointment)
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCheckin(false)}>Cancel</Button>
            <Button onClick={checkIn} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="checkin-confirm-btn">
              <LogIn size={16} className="mr-2" /> Check in
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}