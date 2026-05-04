import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { FileText } from "lucide-react";

export default function PatientChart() {
  const [client, setClient] = React.useState(null);
  const [notes, setNotes] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    (async () => {
      try {
        const me = await api.get("/clients/me");
        setClient(me.data);
        const n = await api.get("/notes", { params: { client_id: me.data.id } });
        setNotes(n.data || []);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <PortalLayout>
      <PortalHeader title="My Chart" subtitle="Visit notes & amendments by your practitioner." />
      {loading ? (
        <div className="text-[#6a6a6a]">Loading…</div>
      ) : notes.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <FileText size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No visit notes yet. Notes will appear here after your appointment.</div>
        </div>
      ) : (
        <div className="space-y-4">
          {notes.map((n) => (
            <article key={n.id} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6">
              <header className="flex flex-col md:flex-row md:items-center md:justify-between mb-3">
                <div className="text-xs tracking-widest uppercase text-[#8a6a3c]">
                  Visit — {new Date(n.created_at).toLocaleString()}
                </div>
                <div className="text-sm text-[#3a3a3a]">By {n.practitioner_name || "Practitioner"}</div>
              </header>
              <SoapField label="Subjective" value={n.subjective} />
              <SoapField label="Objective" value={n.objective} />
              <SoapField label="Assessment" value={n.assessment} />
              <SoapField label="Plan" value={n.plan} />
              {(n.amendments || []).length > 0 && (
                <div className="mt-4 border-t border-[#e7dfc9] pt-3">
                  <div className="eyebrow text-[#8a6a3c] mb-2">Amendments</div>
                  <ul className="space-y-2">
                    {n.amendments.map((a, i) => (
                      <li key={i} className="text-sm text-[#3a3a3a]">
                        <span className="text-[#6a6a6a]">{new Date(a.ts).toLocaleString()} — {a.author_name || "Practitioner"}:</span> {a.content}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </PortalLayout>
  );
}

function SoapField({ label, value }) {
  if (!value) return null;
  return (
    <div className="mb-3">
      <div className="text-[11px] uppercase tracking-widest text-[#8a6a3c]">{label}</div>
      <div className="text-[14px] text-[#2a2a2a] whitespace-pre-wrap leading-relaxed">{value}</div>
    </div>
  );
}
