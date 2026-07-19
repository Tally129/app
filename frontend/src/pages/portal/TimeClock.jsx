import React from "react";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { useToast } from "../../hooks/use-toast";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { Play, Pause, Square, Coffee, Timer as TimerIcon, History } from "lucide-react";
import { getErrorMessage } from "../../lib/errors";

function formatMin(mins) {
  if (mins == null) return "—";
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return `${h}h ${m}m`;
}

function tickElapsed(entry) {
  if (!entry || !entry.clock_in) return 0;
  const start = new Date(entry.clock_in).getTime();
  const end = entry.clock_out ? new Date(entry.clock_out).getTime() : Date.now();
  let mins = (end - start) / 60000;
  for (const b of entry.breaks || []) {
    if (b.start) {
      const bs = new Date(b.start).getTime();
      const be = b.end ? new Date(b.end).getTime() : Date.now();
      mins -= (be - bs) / 60000;
    }
  }
  return Math.max(0, mins);
}

export default function TimeClock() {
  const { user } = useAuth();
  const { toast } = useToast();
  const isAdmin = user?.role === "admin";
  const [mine, setMine] = React.useState([]);
  const [allEntries, setAllEntries] = React.useState([]);
  const [tick, setTick] = React.useState(0);

  const load = async () => {
    try {
      const r = await api.get("/time-clock/me");
      setMine(r.data || []);
      if (isAdmin) {
        const a = await api.get("/time-clock/all");
        setAllEntries(a.data || []);
      }
    } catch (e) {
      toast({ title: "Failed to load", description: getErrorMessage(e) || "" });
    }
  };

  React.useEffect(() => { load(); }, []);
  React.useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 30_000);
    return () => clearInterval(t);
  }, []);

  const open = mine.find((e) => !e.clock_out) || null;
  const onBreak = !!(open && (open.breaks || []).length && !(open.breaks[open.breaks.length - 1].end));

  const punchIn = async () => {
    try { await api.post("/time-clock/punch-in"); toast({ title: "Punched in" }); load(); }
    catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };
  const punchOut = async () => {
    try { await api.post("/time-clock/punch-out"); toast({ title: "Punched out" }); load(); }
    catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };
  const breakStart = async () => {
    try { await api.post("/time-clock/break-start"); toast({ title: "Break started" }); load(); }
    catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };
  const breakEnd = async () => {
    try { await api.post("/time-clock/break-end"); toast({ title: "Break ended" }); load(); }
    catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };

  const editTime = async (e) => {
    const ci = window.prompt("Clock-in (ISO 8601, blank to keep)", e.clock_in || "");
    const co = window.prompt("Clock-out (ISO 8601, blank to keep)", e.clock_out || "");
    const note = window.prompt("Note", e.note || "");
    const payload = {};
    if (ci) payload.clock_in = ci;
    if (co) payload.clock_out = co;
    if (note != null) payload.note = note;
    if (Object.keys(payload).length === 0) return;
    try {
      await api.put(`/time-clock/${e.id}`, payload);
      toast({ title: "Saved" });
      load();
    } catch (err) {
      toast({ title: "Failed", description: getErrorMessage(err) || "" });
    }
  };

  const elapsed = open ? tickElapsed(open) : 0;

  // weekly minutes (last 7 days)
  const weekMs = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const weekMins = mine
    .filter((e) => new Date(e.clock_in).getTime() >= weekMs && e.total_minutes != null)
    .reduce((s, e) => s + e.total_minutes, 0);

  return (
    <PortalLayout>
      <PortalHeader title="Time Clock" subtitle="Punch in, take breaks, view history" />

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <StatCard
          label="Status"
          value={open ? (onBreak ? "On break" : "On shift") : "Clocked out"}
          icon={TimerIcon}
          accent={open ? "text-[#2f4a3a]" : "text-[#8a6a3c]"}
        />
        <StatCard label="Current shift" value={open ? formatMin(elapsed) : "—"} icon={TimerIcon} />
        <StatCard label="Last 7 days" value={formatMin(weekMins)} icon={History} />
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 mb-6 flex flex-wrap gap-3" data-testid="timeclock-controls">
        {!open && (
          <Button onClick={punchIn} className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] h-11" data-testid="punch-in-btn">
            <Play size={16} className="mr-2" /> Punch in
          </Button>
        )}
        {open && !onBreak && (
          <>
            <Button onClick={breakStart} variant="outline" className="rounded-full border-[#c19a4b] text-[#8a6a3c] h-11" data-testid="break-start-btn">
              <Coffee size={16} className="mr-2" /> Start break
            </Button>
            <Button onClick={punchOut} className="btn-lift rounded-full bg-[#7a2a2a] hover:bg-[#5e1f1f] text-[#f6f1e6] h-11" data-testid="punch-out-btn">
              <Square size={16} className="mr-2" /> Punch out
            </Button>
          </>
        )}
        {open && onBreak && (
          <Button onClick={breakEnd} className="btn-lift rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22] h-11" data-testid="break-end-btn">
            <Pause size={16} className="mr-2" /> End break
          </Button>
        )}
      </div>

      <Tabs defaultValue="mine">
        <TabsList className="bg-[#f1ead8]">
          <TabsTrigger value="mine" data-testid="tc-tab-mine">My shifts</TabsTrigger>
          {isAdmin && <TabsTrigger value="all" data-testid="tc-tab-all">All staff (admin)</TabsTrigger>}
        </TabsList>

        <TabsContent value="mine" className="mt-4">
          <ShiftTable rows={mine} onEdit={isAdmin ? editTime : null} />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="all" className="mt-4">
            <ShiftTable rows={allEntries} showName onEdit={editTime} />
          </TabsContent>
        )}
      </Tabs>
    </PortalLayout>
  );
}

function ShiftTable({ rows, showName, onEdit }) {
  return (
    <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
          <tr>
            {showName && <th className="text-left py-3 px-4">Staff</th>}
            <th className="text-left py-3 px-4">Date</th>
            <th className="text-left py-3 px-4">Clock in</th>
            <th className="text-left py-3 px-4">Clock out</th>
            <th className="text-left py-3 px-4">Breaks</th>
            <th className="text-left py-3 px-4">Total</th>
            {onEdit && <th className="text-right py-3 px-4">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={onEdit ? 7 : 6} className="py-8 text-center text-[#6a6a6a]">No entries yet.</td></tr>}
          {rows.map((e) => {
            const ci = e.clock_in ? new Date(e.clock_in) : null;
            const co = e.clock_out ? new Date(e.clock_out) : null;
            const breakMins = (e.breaks || []).reduce((s, b) => {
              if (!b.start || !b.end) return s;
              return s + (new Date(b.end) - new Date(b.start)) / 60000;
            }, 0);
            return (
              <tr key={e.id} className="border-t border-[#e7dfc9]" data-testid={`shift-row-${e.id}`}>
                {showName && <td className="py-3 px-4">{e.user_name || e.user_id}</td>}
                <td className="py-3 px-4 text-[#6a6a6a]">{ci ? ci.toLocaleDateString() : "—"}</td>
                <td className="py-3 px-4">{ci ? ci.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                <td className="py-3 px-4">{co ? co.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : <span className="text-[#2f4a3a]">Active</span>}</td>
                <td className="py-3 px-4 text-[#6a6a6a]">{(e.breaks || []).length} ({Math.round(breakMins)}m)</td>
                <td className="py-3 px-4 font-display text-[#2f4a3a]">{formatMin(e.total_minutes)}</td>
                {onEdit && (
                  <td className="py-3 px-4 text-right">
                    <Button size="sm" variant="outline" className="h-7 rounded-full text-xs border-[#2f4a3a] text-[#2f4a3a]" onClick={() => onEdit(e)} data-testid={`shift-edit-${e.id}`}>Edit</Button>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}