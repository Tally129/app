import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";

function fmt(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

export default function AdminSessionExplorer() {
  const [sessions, setSessions] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [filter, setFilter] = React.useState("");
  const [chain, setChain] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/sessions", { params: { limit: 200 } });
      setSessions(Array.isArray(data) ? data : []);
    } finally {
      setLoading(false);
    }
  }, []);

  const verifyChain = async () => {
    try {
      const { data } = await api.get("/admin/audit/verify-chain?limit=5000");
      setChain(data);
    } catch (e) {
      setChain({ ok: false, error: e?.response?.data?.detail || e.message });
    }
  };

  React.useEffect(() => { load(); }, [load]);

  const revoke = async (id) => {
    if (!window.confirm("Revoke this session? User will be forced to re-authenticate.")) return;
    await api.post(`/admin/sessions/${id}/revoke`);
    await load();
  };

  const revokeAll = async (userId) => {
    if (!window.confirm("Revoke ALL active sessions for this user?")) return;
    await api.post(`/admin/users/${userId}/revoke-all-sessions`);
    await load();
  };

  const filtered = React.useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) =>
      (s.email || "").toLowerCase().includes(q) ||
      (s.full_name || "").toLowerCase().includes(q) ||
      (s.role || "").toLowerCase().includes(q));
  }, [sessions, filter]);

  return (
    <PortalLayout>
      <PortalHeader
        title="Session Explorer"
        subtitle="Active workforce & user sessions. Revocation is audited."
      />
      <div className="flex items-center gap-3 mb-4">
        <Input
          data-testid="session-explorer-filter"
          placeholder="Filter by email, name, or role"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="max-w-xs"
        />
        <Button data-testid="session-explorer-refresh" variant="secondary" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </Button>
        <Button data-testid="session-explorer-verify-chain" variant="outline" onClick={verifyChain}>
          Verify Audit Chain
        </Button>
        {chain && (
          <span
            data-testid="session-explorer-chain-status"
            className={`text-xs px-2 py-1 rounded ${chain.ok ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}
          >
            {chain.ok ? `Chain OK · ${chain.checked} rows` : `Chain broken · ${chain.first_break || chain.error}`}
          </span>
        )}
      </div>
      <div className="overflow-x-auto rounded border border-neutral-200 bg-white">
        <table data-testid="session-explorer-table" className="w-full text-sm">
          <thead className="bg-neutral-50 text-left text-neutral-600">
            <tr>
              <th className="px-3 py-2">User</th>
              <th className="px-3 py-2">Role</th>
              <th className="px-3 py-2">Created</th>
              <th className="px-3 py-2">Last active</th>
              <th className="px-3 py-2">Absolute expiry</th>
              <th className="px-3 py-2">IP (last)</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.id} className="border-t border-neutral-100" data-testid={`session-row-${s.id}`}>
                <td className="px-3 py-2">
                  <div className="font-medium">{s.full_name || "—"}</div>
                  <div className="text-xs text-neutral-500">{s.email || s.user_id}</div>
                </td>
                <td className="px-3 py-2 capitalize">{s.role || "—"}</td>
                <td className="px-3 py-2 whitespace-nowrap">{fmt(s.created_at)}</td>
                <td className="px-3 py-2 whitespace-nowrap">{fmt(s.last_used_at)}</td>
                <td className="px-3 py-2 whitespace-nowrap">{fmt(s.absolute_expires_at)}</td>
                <td className="px-3 py-2">{s.ip_last || s.ip_first || "—"}</td>
                <td className="px-3 py-2 space-x-2">
                  <Button
                    data-testid={`session-revoke-${s.id}`}
                    size="sm"
                    variant="destructive"
                    onClick={() => revoke(s.id)}
                  >
                    Revoke
                  </Button>
                  <Button
                    data-testid={`session-revoke-all-${s.user_id}`}
                    size="sm"
                    variant="outline"
                    onClick={() => revokeAll(s.user_id)}
                  >
                    Revoke all for user
                  </Button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td className="px-3 py-6 text-center text-neutral-500" colSpan={7}>
                  {loading ? "Loading…" : "No active sessions."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}
