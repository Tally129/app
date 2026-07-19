import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { useToast } from "../../hooks/use-toast";
import { ShieldCheck, ExternalLink, Loader2, CheckCircle2, Circle, Clock, XCircle, Save } from "lucide-react";
import { getErrorMessage } from "../../lib/errors";

const STATUS_META = {
  not_started:    { label: "Not started",    color: "bg-[#f5e3e3] text-[#7a2a2a] border-[#d4a8a8]", icon: XCircle },
  requested:      { label: "Requested",      color: "bg-[#f1ead8] text-[#8a6a3c] border-[#e0d6bc]", icon: Clock },
  signed:         { label: "Signed",         color: "bg-[#dde9dd] text-[#2f4a3a] border-[#a8bfa8]", icon: CheckCircle2 },
  not_applicable: { label: "N/A",            color: "bg-[#e7e7e7] text-[#4a4a4a] border-[#c8c8c8]", icon: Circle },
};

export default function AdminCompliance() {
  const { toast } = useToast();
  const [rows, setRows] = React.useState([]);
  const [busy, setBusy] = React.useState({});
  const [notes, setNotes] = React.useState({});

  const load = async () => {
    try { const r = await api.get("/compliance/baa-checklist"); setRows(r.data || []); }
    catch (e) { toast({ title: "Failed to load", description: getErrorMessage(e) || "" }); }
  };
  React.useEffect(() => { load(); }, []);

  const update = async (key, patch) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      const r = await api.put(`/compliance/baa-checklist/${key}`, patch);
      setRows((rs) => rs.map((x) => x.key === key ? r.data : x));
      toast({ title: patch.status === "signed" ? "Marked as signed ✓" : "Updated" });
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
    finally { setBusy((b) => ({ ...b, [key]: false })); }
  };

  const signedCount = rows.filter((r) => r.status === "signed").length;
  const requiredCount = rows.filter((r) => r.required).length;
  const doneCount = rows.filter((r) => r.required && (r.status === "signed" || r.status === "not_applicable")).length;

  return (
    <PortalLayout>
      <PortalHeader
        title="HIPAA Compliance"
        subtitle="Track Business Associate Agreements with every downstream vendor that touches PHI."
      />

      <div className="rounded-2xl border border-[#c19a4b] bg-[#f6f1e6] p-5 mb-6" data-testid="compliance-summary">
        <div className="flex items-start gap-3">
          <ShieldCheck size={22} className="text-[#8a6a3c] mt-0.5" />
          <div className="flex-1">
            <div className="font-display text-xl text-[#1f2a22]">
              {doneCount} of {requiredCount} required BAAs signed
            </div>
            <p className="text-sm text-[#5a5a5a] mt-1">
              {doneCount < requiredCount
                ? "⚠️ You have unsigned BAAs. Do NOT onboard real patients until every required row is signed or marked N/A."
                : "✅ All required BAAs signed. Combined with the technical safeguards in this app, you are ready to onboard real patients."}
            </p>
            <div className="mt-3 h-2 rounded-full bg-[#e7dfc9] overflow-hidden">
              <div className="h-full bg-[#2f4a3a] transition-all" style={{ width: requiredCount ? `${(doneCount / requiredCount) * 100}%` : 0 }} />
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-4" data-testid="compliance-rows">
        {rows.map((r) => {
          const M = STATUS_META[r.status] || STATUS_META.not_started;
          const Icon = M.icon;
          return (
            <div key={r.key} className={`rounded-2xl border bg-[#fbf7ee] p-5 ${r.status === "signed" ? "border-[#a8bfa8]" : r.required ? "border-[#e7dfc9]" : "border-[#e7dfc9] opacity-80"}`} data-testid={`baa-row-${r.key}`}>
              <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center flex-wrap gap-2">
                    <h3 className="font-display text-xl text-[#1f2a22]">{r.vendor}</h3>
                    <span className={`text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border inline-flex items-center gap-1 ${M.color}`}>
                      <Icon size={10} /> {M.label}
                    </span>
                    {!r.required && <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#e7e7e7] text-[#4a4a4a]">Optional</span>}
                  </div>
                  <p className="text-sm text-[#5a5a5a] mt-1">{r.purpose}</p>
                  {r.docs_url && (
                    <a href={r.docs_url} target="_blank" rel="noreferrer" className="text-xs text-[#2f4a3a] hover:underline mt-2 inline-flex items-center gap-1">
                      <ExternalLink size={11} /> Vendor BAA docs
                    </a>
                  )}
                  {r.signed_at && (
                    <div className="text-xs text-[#5b6f5b] mt-2">Signed {new Date(r.signed_at).toLocaleDateString()} by {r.signed_by || "—"}</div>
                  )}
                </div>
                <div className="flex-shrink-0 flex flex-col gap-2 min-w-[220px]">
                  <div className="grid grid-cols-2 gap-2">
                    {["not_started", "requested", "signed", "not_applicable"].map((s) => (
                      <button
                        key={s}
                        onClick={() => update(r.key, { status: s })}
                        disabled={busy[r.key] || r.status === s}
                        className={`h-8 rounded-full text-[10px] uppercase tracking-widest border transition ${
                          r.status === s
                            ? "bg-[#2f4a3a] border-[#2f4a3a] text-[#f6f1e6]"
                            : "bg-[#f6f1e6] border-[#e0d6bc] text-[#3a3a3a] hover:bg-[#f1ead8]"
                        }`}
                        data-testid={`baa-${r.key}-status-${s}`}
                      >
                        {STATUS_META[s].label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="mt-4 pt-3 border-t border-[#e7dfc9]">
                <div className="flex items-start gap-2">
                  <Textarea
                    className="bg-[#f6f1e6] border-[#e0d6bc] flex-1 text-xs"
                    rows={2}
                    placeholder="Internal notes (executed date, DocuSign envelope id, next renewal, etc.)"
                    value={notes[r.key] !== undefined ? notes[r.key] : (r.notes || "")}
                    onChange={(e) => setNotes((n) => ({ ...n, [r.key]: e.target.value }))}
                    data-testid={`baa-${r.key}-notes`}
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => update(r.key, { notes: notes[r.key] || "" })}
                    disabled={busy[r.key]}
                    data-testid={`baa-${r.key}-save-notes`}
                  >
                    {busy[r.key] ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                  </Button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-8 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 text-sm text-[#3a3a3a]" data-testid="compliance-tech-checklist">
        <div className="font-display text-lg text-[#1f2a22] mb-2 inline-flex items-center gap-2"><ShieldCheck size={16} className="text-[#2f4a3a]" /> Technical safeguards in place</div>
        <ul className="space-y-1 mt-2 text-xs text-[#5a5a5a]">
          <li>✅ Session inactivity auto-logout (15 min)</li>
          <li>✅ NIST-modern password policy (12+ chars, common-password reject, no forced rotation)</li>
          <li>✅ Break-glass audit role — all reads stamped emergency=true</li>
          <li>✅ HSTS + secure headers enforced (Strict-Transport-Security 1yr, X-Frame-Options DENY)</li>
          <li>✅ Immutable audit log on every mutation + break-glass read</li>
          <li>✅ §164.524 patient data export</li>
          <li>✅ §164.528 accounting of disclosures</li>
          <li>✅ Full RBAC across every endpoint</li>
          <li>⚠️ Encryption at rest depends on your MongoDB Atlas tier (M10+ with BAA required)</li>
        </ul>
      </div>
    </PortalLayout>
  );
}