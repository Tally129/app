import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { Textarea } from "../../components/ui/textarea";
import { useToast } from "../../hooks/use-toast";
import { Leaf, CheckCircle2, XCircle, Loader2, Sparkles, Clock, ListChecks } from "lucide-react";
import { EnrollmentDialog } from "../portal/Protocols";
import { getErrorMessage } from "../../lib/errors";

/**
 * Patient view of their proposed and active protocols.
 * • Proposed: large Accept / Decline buttons.
 * • Active/Completed: open the read-only sessions grid (server-side blocks edits).
 */
export default function PatientProtocols() {
  const { toast } = useToast();
  const [enrollments, setEnrollments] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [openEnr, setOpenEnr] = React.useState(null);
  const [decideTarget, setDecideTarget] = React.useState(null);
  const [decideKind, setDecideKind] = React.useState(""); // accept|decline
  const [note, setNote] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  const load = async () => {
    setLoading(true);
    try { const r = await api.get("/protocols/enrollments"); setEnrollments(r.data || []); }
    finally { setLoading(false); }
  };
  React.useEffect(() => { load(); }, []);

  const proposed = enrollments.filter((e) => e.status === "proposed");
  const active = enrollments.filter((e) => e.status === "active" || e.status === "accepted");
  const past = enrollments.filter((e) => e.status === "completed" || e.status === "declined" || e.status === "canceled");

  const decide = async () => {
    if (!decideTarget) return;
    setSubmitting(true);
    try {
      await api.post(`/protocols/enrollments/${decideTarget.id}/decision`, {
        decision: decideKind, note: note || null,
      });
      toast({ title: decideKind === "accept" ? "Protocol accepted!" : "Protocol declined" });
      setDecideTarget(null); setNote(""); setDecideKind("");
      load();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
    finally { setSubmitting(false); }
  };

  return (
    <PortalLayout>
      <PortalHeader title="My Protocols" subtitle="Review proposed wellness protocols and track your progress." />

      {loading ? (
        <div className="text-center py-16 text-[#6a6a6a]"><Loader2 className="inline animate-spin mr-2" size={16} /> Loading…</div>
      ) : enrollments.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-16 text-center text-[#6a6a6a]">
          <Leaf size={28} className="mx-auto text-[#5b6f5b] mb-3" />
          You have no protocols yet. Your provider will propose one here when ready.
        </div>
      ) : (
        <div className="space-y-8">
          {/* Awaiting accept */}
          {proposed.length > 0 && (
            <section data-testid="patient-protocols-proposed">
              <h2 className="font-display text-2xl text-[#1f2a22] mb-3">Awaiting your acceptance</h2>
              <div className="space-y-3">
                {proposed.map((e) => (
                  <div key={e.id} className="rounded-2xl border-2 border-[#c19a4b] bg-[#f6f1e6] p-6" data-testid={`patient-proposed-${e.id}`}>
                    <div className="flex items-start gap-3">
                      <Sparkles size={22} className="text-[#c19a4b] mt-1" />
                      <div className="flex-1 min-w-0">
                        <h3 className="font-display text-xl text-[#1f2a22]">{e.template_title}</h3>
                        <p className="text-sm text-[#5a5a5a] mt-1">
                          {e.weeks} weeks · {e.sessions_per_week}× per week · {e.weeks * e.sessions_per_week} total sessions
                        </p>
                        {e.custom_note && (
                          <div className="mt-3 text-sm text-[#3a3a3a] italic border-l-2 border-[#c19a4b] pl-3">"{e.custom_note}"</div>
                        )}
                        <div className="text-xs text-[#6a6a6a] mt-3">Proposed by {e.created_by_name || "—"} on {new Date(e.proposed_at).toLocaleDateString()}.</div>
                      </div>
                    </div>
                    <div className="mt-5 flex flex-wrap gap-2">
                      <Button onClick={() => setOpenEnr(e)} variant="outline" className="rounded-full" data-testid={`patient-view-${e.id}`}>
                        <ListChecks size={14} className="mr-1.5" /> View details
                      </Button>
                      <Button onClick={() => { setDecideTarget(e); setDecideKind("accept"); }} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid={`patient-accept-${e.id}`}>
                        <CheckCircle2 size={14} className="mr-1.5" /> Accept protocol
                      </Button>
                      <Button onClick={() => { setDecideTarget(e); setDecideKind("decline"); }} variant="outline" className="rounded-full border-[#7a2a2a] text-[#7a2a2a]" data-testid={`patient-decline-${e.id}`}>
                        <XCircle size={14} className="mr-1.5" /> Decline
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Active */}
          {active.length > 0 && (
            <section data-testid="patient-protocols-active">
              <h2 className="font-display text-2xl text-[#1f2a22] mb-3">Active protocols</h2>
              <div className="grid md:grid-cols-2 gap-4">
                {active.map((e) => {
                  const total = (e.sessions || []).length;
                  const done = (e.sessions || []).filter((s) => s.completed).length;
                  return (
                    <button
                      key={e.id}
                      onClick={() => setOpenEnr(e)}
                      className="text-left rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 hover:bg-[#f1ead8] transition"
                      data-testid={`patient-active-${e.id}`}
                    >
                      <div className="flex items-start gap-2 mb-2">
                        <Leaf size={18} className="text-[#5b6f5b] mt-0.5" />
                        <h3 className="font-display text-lg text-[#1f2a22] leading-tight">{e.template_title}</h3>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-[#3a3a3a] mb-3">
                        <Clock size={11} /> {done} of {total} sessions
                      </div>
                      <div className="h-2 rounded-full bg-[#e7dfc9] overflow-hidden">
                        <div className="h-full bg-[#2f4a3a] transition-all" style={{ width: total ? `${(done / total) * 100}%` : 0 }} />
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          {/* History */}
          {past.length > 0 && (
            <section data-testid="patient-protocols-history">
              <h2 className="font-display text-2xl text-[#1f2a22] mb-3">History</h2>
              <ul className="divide-y divide-[#e7dfc9] rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee]">
                {past.map((e) => (
                  <li key={e.id} className="px-5 py-4 flex items-center justify-between">
                    <div>
                      <div className="font-medium text-[#1f2a22]">{e.template_title}</div>
                      <div className="text-xs text-[#6a6a6a] mt-0.5">{e.status} · {new Date(e.proposed_at).toLocaleDateString()}</div>
                    </div>
                    <button onClick={() => setOpenEnr(e)} className="text-xs text-[#2f4a3a] hover:underline">View</button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      <EnrollmentDialog enrollment={openEnr} onOpenChange={(v) => !v && setOpenEnr(null)} viewOnly />

      <Dialog open={!!decideTarget} onOpenChange={(v) => !v && setDecideTarget(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">{decideKind === "accept" ? "Accept protocol" : "Decline protocol"}</DialogTitle>
            <DialogDescription>
              {decideKind === "accept"
                ? "By accepting, this protocol will be attached to your chart and your provider will track your sessions here."
                : "Let your provider know why if you'd like — they'll follow up to discuss alternatives."}
            </DialogDescription>
          </DialogHeader>
          <div>
            <Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={decideKind === "accept" ? "Anything you'd like your provider to know? (optional)" : "Reason for declining (optional)"} data-testid="patient-decision-note" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDecideTarget(null)}>Cancel</Button>
            <Button
              onClick={decide}
              disabled={submitting}
              className={`rounded-full ${decideKind === "accept" ? "bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" : "bg-[#7a2a2a] hover:bg-[#5a1d1d] text-[#f6f1e6]"}`}
              data-testid="patient-decision-submit"
            >
              {submitting ? <Loader2 size={14} className="animate-spin mr-1" /> : null}
              {decideKind === "accept" ? "Yes, accept protocol" : "Decline"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}