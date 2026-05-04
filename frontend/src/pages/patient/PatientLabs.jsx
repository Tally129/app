import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { TestTube2 } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea } from "recharts";

export default function PatientLabs() {
  const [labs, setLabs] = React.useState([]);
  const [presets, setPresets] = React.useState([]);

  React.useEffect(() => {
    api.get("/lab-values").then((r) => setLabs(r.data || []));
    api.get("/labs/presets").then((r) => setPresets(r.data.presets || []));
  }, []);

  const byTest = React.useMemo(() => {
    const g = {};
    for (const l of labs) {
      (g[l.test_name] = g[l.test_name] || []).push({
        date: new Date(l.measured_at).toLocaleDateString(),
        t: new Date(l.measured_at).getTime(),
        value: l.value,
        ref_low: l.reference_low,
        ref_high: l.reference_high,
        unit: l.unit,
      });
    }
    Object.values(g).forEach((arr) => arr.sort((a, b) => a.t - b.t));
    return g;
  }, [labs]);

  return (
    <PortalLayout>
      <PortalHeader title="Lab Results" subtitle="Recorded by your care team. Trends help spot progress over time." />
      {Object.keys(byTest).length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <TestTube2 size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No lab results yet.</div>
        </div>
      ) : (
        <div className="space-y-5">
          {Object.entries(byTest).map(([name, data]) => {
            const latest = data[data.length - 1];
            return (
              <div key={name} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="font-display text-xl text-[#1f2a22]">{name}</div>
                    <div className="text-xs text-[#6a6a6a]">Latest: {latest.value} {latest.unit || ""} on {latest.date}</div>
                  </div>
                  {latest.ref_low != null && latest.ref_high != null && (
                    <div className="text-xs text-[#8a6a3c]">ref {latest.ref_low} – {latest.ref_high}</div>
                  )}
                </div>
                <div style={{ width: "100%", height: 180 }}>
                  <ResponsiveContainer>
                    <LineChart data={data} margin={{ top: 10, right: 16, bottom: 10, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e7dfc9" />
                      <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6a6a6a" }} />
                      <YAxis tick={{ fontSize: 11, fill: "#6a6a6a" }} />
                      {latest.ref_low != null && latest.ref_high != null && (
                        <ReferenceArea y1={latest.ref_low} y2={latest.ref_high} fill="#c19a4b" fillOpacity={0.12} />
                      )}
                      <Tooltip contentStyle={{ background: "#fbf7ee", border: "1px solid #e7dfc9", borderRadius: 8, fontSize: 12 }} />
                      <Line type="monotone" dataKey="value" stroke="#2f4a3a" strokeWidth={2} dot={{ r: 4, fill: "#c19a4b" }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </PortalLayout>
  );
}
