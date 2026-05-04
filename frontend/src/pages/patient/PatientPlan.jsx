import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Eye, Pill, Apple, Moon, TestTube2, CalendarCheck } from "lucide-react";

const TYPE_META = {
  supplement: { icon: Pill, label: "Supplement" },
  diet: { icon: Apple, label: "Diet" },
  lifestyle: { icon: Moon, label: "Lifestyle" },
  lab_order: { icon: TestTube2, label: "Lab order" },
  follow_up: { icon: CalendarCheck, label: "Follow-up" },
};

export default function PatientPlan() {
  const [plans, setPlans] = React.useState([]);
  React.useEffect(() => { api.get("/treatment-plans").then((r) => setPlans(r.data || [])); }, []);

  return (
    <PortalLayout>
      <PortalHeader title="Treatment Plan" subtitle="Your personalized protocol from Dr. Ravello’s team." />
      {plans.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          No active treatment plan yet. Your practitioner will build one after your visit.
        </div>
      ) : (
        <div className="space-y-6">
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
