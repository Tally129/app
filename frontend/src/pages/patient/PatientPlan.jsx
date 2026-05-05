import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Pill, Apple, Moon, TestTube2, CalendarCheck, Sparkles } from "lucide-react";

const TYPE_META = {
  supplement: { icon: Pill, label: "Supplement" },
  diet: { icon: Apple, label: "Diet" },
  lifestyle: { icon: Moon, label: "Lifestyle" },
  lab_order: { icon: TestTube2, label: "Lab order" },
  follow_up: { icon: CalendarCheck, label: "Follow-up" },
};

export default function PatientPlan() {
  const { user } = useAuth();
  const [plans, setPlans] = React.useState([]);
  const [supplements, setSupplements] = React.useState([]);

  React.useEffect(() => {
    api.get("/treatment-plans").then((r) => setPlans(r.data || [])).catch(() => {});
  }, []);

  // Resolve the patient's own client_id to fetch their supplement assignments
  React.useEffect(() => {
    let active = true;
    (async () => {
      try {
        const r = await api.get("/clients/me");
        const me = r.data;
        if (!me?.id || !active) return;
        const a = await api.get(`/clients/${me.id}/supplement-assignments`);
        if (active) setSupplements(a.data || []);
      } catch {
        // graceful fallback
      }
    })();
    return () => { active = false; };
  }, [user]);

  return (
    <PortalLayout>
      <PortalHeader title="Treatment Plan" subtitle="Your personalized protocol from Dr. Ravello's team." />

      {/* Auto-attached supplement directions */}
      {supplements.length > 0 && (
        <section className="mb-8" data-testid="patient-supplement-assignments">
          <div className="flex items-end justify-between mb-3">
            <h2 className="font-display text-2xl text-[#1f2a22] flex items-center gap-2">
              <Pill size={18} className="text-[#8a6a3c]" /> Your supplement directions
            </h2>
            <span className="text-xs uppercase tracking-widest text-[#8a6a3c]">{supplements.length} sheet{supplements.length === 1 ? "" : "s"}</span>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {supplements.map((s) => (
              <article key={s.id} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5" data-testid={`patient-supp-${s.id}`}>
                <div className="flex items-start gap-2 mb-2">
                  <div className="rounded-full bg-[#f1ead8] p-2 text-[#8a6a3c] flex-shrink-0"><Pill size={14} /></div>
                  <div className="flex-1 min-w-0">
                    <div className="font-display text-lg text-[#1f2a22] leading-tight">{s.sheet_title}</div>
                    <div className="text-xs text-[#6a6a6a] mt-0.5">
                      Assigned by {s.assigned_by_name || "your provider"} · {new Date(s.assigned_at).toLocaleDateString()}
                      {s.source === "auto_soap" && (
                        <span className="ml-2 inline-flex items-center gap-1 text-[#c19a4b]"><Sparkles size={10} /> auto-attached</span>
                      )}
                    </div>
                  </div>
                </div>
                {s.sheet_summary && <p className="text-sm text-[#5a5a5a] mb-3 line-clamp-2">{s.sheet_summary}</p>}
                {(s.items_snapshot || []).length > 0 && (
                  <ul className="text-xs text-[#3a3a3a] space-y-1 border-t border-[#e7dfc9] pt-3">
                    {(s.items_snapshot || []).slice(0, 6).map((it, idx) => (
                      <li key={idx} className="flex justify-between gap-3">
                        <span className="font-medium truncate">{it.name}</span>
                        <span className="text-[#6a6a6a] flex-shrink-0">{[it.dose, it.frequency, it.timing].filter(Boolean).join(" · ")}</span>
                      </li>
                    ))}
                    {(s.items_snapshot || []).length > 6 && <li className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">+{s.items_snapshot.length - 6} more</li>}
                  </ul>
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      {/* Treatment plans (existing) */}
      {plans.length === 0 && supplements.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          No active treatment plan yet. Your practitioner will build one after your visit.
        </div>
      ) : plans.length === 0 ? null : (
        <div className="space-y-6" data-testid="patient-treatment-plans">
          {plans.map((p) => (
            <article key={p.id} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6">
              <header className="mb-4">
                <div className="font-display text-2xl text-[#1f2a22]">{p.title}</div>
                <div className="text-xs text-[#6a6a6a] mt-1">Created {new Date(p.created_at).toLocaleDateString()} by {p.practitioner_name || "—"}</div>
                {p.follow_up_days && <div className="text-xs text-[#8a6a3c] mt-1">Follow up in {p.follow_up_days} days</div>}
              </header>
              {p.items.length === 0 ? (
                <div className="text-sm text-[#6a6a6a]">No items shared with you yet.</div>
              ) : (
                <ul className="space-y-3">
                  {p.items.map((it, i) => {
                    const M = TYPE_META[it.type] || TYPE_META.lifestyle;
                    const Icon = M.icon;
                    return (
                      <li key={i} className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-full bg-[#2f4a3a] text-[#f6f1e6] flex items-center justify-center shrink-0"><Icon size={14} /></div>
                        <div className="flex-1">
                          <div className="font-medium text-[#1f2a22]">{it.title}</div>
                          <div className="text-xs tracking-widest uppercase text-[#8a6a3c]">{M.label}</div>
                          {(it.dose || it.frequency || it.duration) && (
                            <div className="text-sm text-[#3a3a3a] mt-1">{[it.dose, it.frequency, it.duration].filter(Boolean).join(" · ")}</div>
                          )}
                          {it.detail && <div className="text-sm text-[#5a5a5a] mt-1 leading-relaxed">{it.detail}</div>}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </article>
          ))}
        </div>
      )}
    </PortalLayout>
  );
}
