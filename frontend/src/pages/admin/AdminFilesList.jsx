import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Input } from "../../components/ui/input";
import { FileText, Search, Loader2, Download } from "lucide-react";

export default function AdminFilesList() {
  const [rows, setRows] = React.useState([]);
  const [search, setSearch] = React.useState("");
  const [loading, setLoading] = React.useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/files");
      setRows(r.data || []);
    } finally { setLoading(false); }
  };
  React.useEffect(() => { load(); }, []);

  const filtered = rows.filter((f) =>
    !search ||
    (f.filename || "").toLowerCase().includes(search.toLowerCase()) ||
    (f.uploaded_by_name || "").toLowerCase().includes(search.toLowerCase())
  );

  const formatBytes = (b) => {
    if (!b) return "—";
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / 1024 / 1024).toFixed(1)} MB`;
  };

  return (
    <PortalLayout>
      <PortalHeader title="Files" subtitle="Clinic-wide file vault. Click to download." />
      <div className="relative max-w-md mb-5">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
        <Input
          placeholder="Search by filename or uploader…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9 bg-[#f6f1e6] border-[#e0d6bc]"
          data-testid="admin-files-search"
        />
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="admin-files-table">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Uploaded</th>
              <th className="text-left py-3 px-4">Filename</th>
              <th className="text-left py-3 px-4">Category</th>
              <th className="text-left py-3 px-4">Uploaded by</th>
              <th className="text-right py-3 px-4">Size</th>
              <th className="text-right py-3 px-4">—</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} className="py-10 text-center text-[#6a6a6a]"><Loader2 className="inline animate-spin mr-2" size={14} /> Loading…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={6} className="py-12 text-center text-[#6a6a6a]">No files match.</td></tr>
            )}
            {!loading && filtered.map((f) => (
              <tr key={f.id} className="border-t border-[#e7dfc9] hover:bg-[#f1ead8]" data-testid={`admin-file-row-${f.id}`}>
                <td className="py-3 px-4 text-xs text-[#6a6a6a]">
                  {new Date(f.created_at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
                </td>
                <td className="py-3 px-4 font-medium text-[#1f2a22] truncate max-w-xs"><FileText size={12} className="inline mr-1.5 text-[#8a6a3c]" />{f.filename}</td>
                <td className="py-3 px-4 text-[#3a3a3a]"><span className="text-xs uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#f1ead8] border border-[#e0d6bc]">{f.category}</span></td>
                <td className="py-3 px-4 text-[#3a3a3a]">{f.uploaded_by_name || "—"}</td>
                <td className="py-3 px-4 text-right text-[#6a6a6a] text-xs">{formatBytes(f.size)}</td>
                <td className="py-3 px-4 text-right">
                  <a href={`${api.defaults.baseURL}/files/${f.id}/download`} target="_blank" rel="noreferrer" className="text-[#2f4a3a] hover:underline inline-flex items-center gap-1 text-xs">
                    <Download size={12} /> Download
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}
