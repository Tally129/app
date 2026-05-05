import React from "react";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
  BarChart, Bar, PieChart, Pie, Cell, Legend,
} from "recharts";
import { TrendingUp, Calendar, Users, AlertTriangle, Stethoscope, FileText } from "lucide-react";

const COLORS = ["#2f4a3a", "#c19a4b", "#7a2a2a", "#5b8a5b", "#8a6a3c", "#a8853f", "#406352"];

const METHOD_LABELS = {
  chase_pos: "Chase POS", cash: "Cash", check: "Check", card_other: "Card", stripe: "Stripe",
};

export default function Analytics() {
  const [days, setDays] = React.useState(30);
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    setLoading(true);
    api.get(`/analytics/overview?days=${days}`)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  }, [days]);

  const methodPie = data ? Object.entries(data.revenue.by_method || {}).map(([k, v]) => ({
    name: METHOD_LABELS[k] || k, value: v,
  })) : [];

  return (
    <PortalLayout>
      <PortalHeader
        title="Analytics"
        subtitle="Practice performance · revenue · client trends"
        actions={
          <Select value={String(days)} onValueChange={(v) => setDays(parseInt(v))}>
            <SelectTrigger className="w-40 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="analytics-window-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
              <SelectItem value="90">Last 90 days</SelectItem>
              <SelectItem value="365">Last 12 months</SelectItem>
            </SelectContent>
          </Select>
        }
      />

      {loading && <div className="text-[#6a6a6a] py-12 text-center">Loading…</div>}
      {!loading && data && (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard label="Revenue" value={`$${(data.revenue.total || 0).toLocaleString()}`} icon={TrendingUp} />
            <StatCard label="Appointments" value={data.appointments.total} icon={Calendar} />
            <StatCard
              label="No-show rate"
              value={`${data.appointments.no_show_rate}%`}
              icon={AlertTriangle}
              accent={data.appointments.no_show_rate > 10 ? "text-[#7a2a2a]" : "text-[#2f4a3a]"}
            />
            <StatCard label="New clients" value={data.clients.new_clients} icon={Users} />
          </div>

          <div className="grid lg:grid-cols-3 gap-6 mb-8">
            <div className="lg:col-span-2 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5" data-testid="analytics-revenue-chart">
              <div className="eyebrow text-[#8a6a3c] mb-4">Revenue trend</div>
              {data.revenue.series.length === 0 ? (
                <div className="text-sm text-[#6a6a6a] py-12 text-center">No revenue in this window</div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={data.revenue.series}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e7dfc9" />
                    <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} stroke="#8a6a3c" fontSize={11} />
                    <YAxis stroke="#8a6a3c" fontSize={11} />
                    <Tooltip contentStyle={{ background: "#fbf7ee", border: "1px solid #e7dfc9" }} />
                    <Line type="monotone" dataKey="revenue" stroke="#2f4a3a" strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow text-[#8a6a3c] mb-4">Revenue by method</div>
              {methodPie.length === 0 ? (
                <div className="text-sm text-[#6a6a6a] py-12 text-center">No data</div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie data={methodPie} dataKey="value" nameKey="name" outerRadius={80} innerRadius={40} paddingAngle={2}>
                      {methodPie.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "#fbf7ee", border: "1px solid #e7dfc9" }} formatter={(v) => `$${v.toFixed(2)}`} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <div className="grid lg:grid-cols-2 gap-6 mb-8">
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5" data-testid="analytics-top-treatments">
              <div className="eyebrow text-[#8a6a3c] mb-4">Top treatments by revenue</div>
              {data.top_treatments.length === 0 ? (
                <div className="text-sm text-[#6a6a6a] py-12 text-center">No treatment sales yet</div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={data.top_treatments} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#e7dfc9" />
                    <XAxis type="number" stroke="#8a6a3c" fontSize={11} />
                    <YAxis type="category" dataKey="name" stroke="#8a6a3c" fontSize={11} width={120} />
                    <Tooltip contentStyle={{ background: "#fbf7ee", border: "1px solid #e7dfc9" }} formatter={(v) => `$${v.toFixed(2)}`} />
                    <Bar dataKey="revenue" fill="#c19a4b" radius={[0, 6, 6, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow text-[#8a6a3c] mb-4 flex items-center gap-2">
                <FileText size={14} /> Notes by provider
              </div>
              {data.notes_by_provider.length === 0 ? (
                <div className="text-sm text-[#6a6a6a] py-12 text-center">No notes recorded</div>
              ) : (
                <ul className="divide-y divide-[#e7dfc9]">
                  {data.notes_by_provider.map((p) => (
                    <li key={p.provider_id} className="py-2.5 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Stethoscope size={14} className="text-[#2f4a3a]" />
                        <span className="text-sm text-[#1f2a22]">{p.provider_name}</span>
                      </div>
                      <span className="font-display text-lg text-[#2f4a3a]">{p.notes}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="grid sm:grid-cols-3 gap-4">
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow text-[#8a6a3c] mb-2">Avg visit duration</div>
              <div className="font-display text-3xl text-[#1f2a22]">{data.appointments.avg_duration_min || 0} <span className="text-sm text-[#6a6a6a]">min</span></div>
            </div>
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow text-[#8a6a3c] mb-2">Completed</div>
              <div className="font-display text-3xl text-[#2f4a3a]">{data.appointments.completed}</div>
            </div>
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow text-[#8a6a3c] mb-2">Low stock items</div>
              <div className={`font-display text-3xl ${data.low_stock_items ? "text-[#7a2a2a]" : "text-[#2f4a3a]"}`}>{data.low_stock_items}</div>
            </div>
          </div>
        </>
      )}
    </PortalLayout>
  );
}
