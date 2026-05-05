import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { FileText, Search, Loader2 } from "lucide-react";

export default function AdminNotesList() {
  const [rows, setRows] = React.useState([]);
  const [providers, setProviders] = React.useState([]);
  const [providerFilter, setProviderFilter] = React.useState("all");
  const [search, setSearch] = React.useState("");
  const [loading, setLoading] = React.useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (providerFilter && providerFilter !== "all") params.practitioner_id = providerFilter;
      if (search) params.search = search;
      const r = await api.get("/notes/all", { params });
      setRows(r.data || []);
    } finally { setLoading(false); }
  };
  React.useEffect(() => {
    api.get("/practitioners").then((r) => setProviders(r.data || [])).catch(() => {});
  }, []);
  React.useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [providerFilter, search]);

  return (
    <PortalLayout>
      <PortalHeader
        title="Visit notes"
        subtitle="Clinic-wide SOAP note index. Click a row to open the client chart."
      />
      <div className="flex flex-col md:flex-row gap-3 mb-5">
        <div className="relative flex-1 max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
          <Input
            placeholder="Search by client name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-[#f6f1e6] border-[#e0d6bc]"
            data-testid="admin-notes-search"
          />
        </div>
        <Select value={providerFilter} onValueChange={setProviderFilter}>
          <SelectTrigger className="w-56 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="admin-notes-provider-filter">
            <SelectValue placeholder="All providers" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All providers</SelectItem>
            {providers.map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name || p.email}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="admin-notes-table">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Date</th>
              <th className="text-left py-3 px-4">Client</th>
              <th className="text-left py-3 px-4">Provider</th>
              <th className="text-left py-3 px-4">Subjective preview</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={4} className="py-10 text-center text-[#6a6a6a]"><Loader2 className="inline animate-spin mr-2" size={14} /> Loading…</td></tr>}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={4} className="py-12 text-center text-[#6a6a6a]">No notes match.</td></tr>
            )}
            {!loading && rows.map((n) => (
              <tr key={n.id} className="border-t border-[#e7dfc9] hover:bg-[#f1ead8]" data-testid={`admin-note-row-${n.id}`}>
                <td className="py-3 px-4 text-xs text-[#6a6a6a]">
                  {new Date(n.created_at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
                </td>
                <td className="py-3 px-4 font-medium text-[#1f2a22]">
                  <Link to={`/portal/provider/patients/${n.client_id}`} className="hover:underline inline-flex items-center gap-1.5">
                    <FileText size={12} className="text-[#8a6a3c]" /> {n.client_name || n.client_id}
                  </Link>
                </td>
                <td className="py-3 px-4 text-[#3a3a3a]">{n.practitioner_name || "—"}</td>
                <td className="py-3 px-4 text-[#6a6a6a] truncate max-w-md">{(n.subjective || "").slice(0, 120) || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}
