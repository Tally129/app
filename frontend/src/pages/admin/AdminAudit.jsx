import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";

const ACTIONS = [
  "_all_",
  "auth.login",
  "auth.register",
  "auth.logout",
  "auth.mfa_enabled",
  "client.create",
  "client.read",
  "client.update",
  "intake.save",
  "intake.read",
  "note.create",
  "note.amend",
  "note.list",
  "file.upload",
  "file.download",
  "admin.create_user",
  "admin.update_role",
];

export default function AdminAudit() {
  const [items, setItems] = React.useState([]);
  const [filter, setFilter] = React.useState({ action: "_all_", q: "" });
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(() => {
    setLoading(true);
    const params = { limit: 300 };
    if (filter.action && filter.action !== "_all_") params.action = filter.action;
    api.get("/admin/audit", { params }).then((r) => setItems(r.data || [])).finally(() => setLoading(false));
  }, [filter.action]);

  React.useEffect(() => { load(); }, [load]);

  const filtered = items.filter((i) => {
    const s = filter.q.toLowerCase();
    if (!s) return true;
    return (
      (i.user_email || "").toLowerCase().includes(s) ||
      (i.action || "").toLowerCase().includes(s) ||
      (i.resource_id || "").toLowerCase().includes(s)
    );
  });

  return (
    <PortalLayout>
      <PortalHeader title="Audit Log" subtitle="Immutable record of PHI operations" />

      <div className="flex flex-col md:flex-row gap-3 mb-5">
        <Input
          placeholder="Search email, action, resource…"
          value={filter.q}
          onChange={(e) => setFilter({ ...filter, q: e.target.value })}
          className="bg-[#fbf7ee] border-[#e0d6bc] max-w-md"
        />
        <Select value={filter.action} onValueChange={(v) => setFilter({ ...filter, action: v })}>
          <SelectTrigger className="w-56 bg-[#fbf7ee] border-[#e0d6bc]">
            <SelectValue placeholder="Filter by action" />
          </SelectTrigger>
          <SelectContent>
            {ACTIONS.map((a) => (
              <SelectItem key={a} value={a}>{a === "_all_" ? "All actions" : a}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Timestamp</th>
              <th className="text-left py-3 px-4">User</th>
              <th className="text-left py-3 px-4">Action</th>
              <th className="text-left py-3 px-4">Resource</th>
              <th className="text-left py-3 px-4">IP</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={5} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={5} className="py-8 text-center text-[#6a6a6a]">No audit events.</td></tr>
            )}
            {filtered.map((i) => (
              <tr key={i.id} className="border-t border-[#e7dfc9]">
                <td className="py-3 px-4 text-[#6a6a6a] whitespace-nowrap">{new Date(i.ts).toLocaleString()}</td>
                <td className="py-3 px-4">{i.user_email || "—"}</td>
                <td className="py-3 px-4"><span className="inline-block px-2 py-0.5 rounded-full bg-[#f1ead8] text-[#2f4a3a] text-xs">{i.action}</span></td>
                <td className="py-3 px-4 text-[#3a3a3a] text-xs">
                  {i.resource_type ? `${i.resource_type}:${(i.resource_id || "").slice(0, 8)}…` : "—"}
                </td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">{i.ip || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}
