import React from "react";
import api from "../lib/api";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

export default function SymptomTrends({ clientId }) {
  const [logs, setLogs] = React.useState([]);
  React.useEffect(() => {
    api.get("/symptom-logs", { params: { client_id: clientId } }).then((r) => setLogs(r.data || []));
  }, [clientId]);

  const byName = React.useMemo(() => {
    const g = {};
    for (const l of logs) {
      (g[l.symptom] = g[l.symptom] || []).push({
        date: new Date(l.logged_at).toLocaleDateString(),
        t: new Date(l.logged_at).getTime(),
        severity: l.severity,
      });
    }
    Object.values(g).forEach((arr) => arr.sort((a, b) => a.t - b.t));
    return g;
  }, [logs]);

  if (Object.keys(byName).length === 0) {
    return <div className="text-sm text-[#6a6a6a]">Patient hasn’t logged any symptoms yet.</div>;
  }

  return (
    <div className="grid md:grid-cols-2 gap-4">
      {Object.entries(byName).map(([name, data]) => (
        <div key={name} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4">
          <div className="text-sm font-medium text-[#1f2a22] mb-1">{name}</div>
          <div className="text-xs text-[#6a6a6a] mb-2">{data.length} entries · latest {data[data.length - 1].severity}/10</div>
          <div style={{ width: "100%", height: 140 }}>
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 6, right: 10, bottom: 6, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e7dfc9" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#6a6a6a" }} />
                <YAxis domain={[1, 10]} tick={{ fontSize: 10, fill: "#6a6a6a" }} />
                <Tooltip contentStyle={{ background: "#fbf7ee", border: "1px solid #e7dfc9", borderRadius: 8, fontSize: 12 }} />
                <Line type="monotone" dataKey="severity" stroke="#2f4a3a" strokeWidth={2} dot={{ r: 3, fill: "#c19a4b" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ))}
    </div>
  );
}
