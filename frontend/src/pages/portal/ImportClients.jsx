import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { useToast } from "../../hooks/use-toast";
import { Upload, FileSpreadsheet, CheckCircle2, AlertCircle } from "lucide-react";

const SUPPORTED = ["full_name", "email", "phone", "dob", "sex", "address", "emergency_contact"];

export default function ImportClients() {
  const { toast } = useToast();
  const [file, setFile] = React.useState(null);
  const [preview, setPreview] = React.useState({ headers: [], rows: [] });
  const [submitting, setSubmitting] = React.useState(false);
  const [result, setResult] = React.useState(null);

  const onFile = async (f) => {
    setFile(f);
    setResult(null);
    if (!f) { setPreview({ headers: [], rows: [] }); return; }
    const text = await f.text();
    const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter(Boolean);
    if (lines.length === 0) return;
    const headers = lines[0].split(",").map((h) => h.trim());
    const rows = lines.slice(1, 6).map((line) => line.split(","));
    setPreview({ headers, rows });
  };

  const upload = async () => {
    if (!file) return;
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post("/clients/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(r.data);
      toast({ title: `Imported ${r.data.imported} · skipped ${r.data.skipped}` });
    } catch (e) {
      toast({ title: "Import failed", description: e?.response?.data?.detail || "" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <PortalLayout>
      <PortalHeader title="Import Clients" subtitle="Bulk-load clients from a CSV file (admin only)" />

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 mb-6">
        <div className="eyebrow text-[#8a6a3c] mb-3">Required CSV format</div>
        <p className="text-sm text-[#3a3a3a] mb-3">
          First row must contain headers. Recognized columns:
        </p>
        <div className="flex flex-wrap gap-2 mb-3">
          {SUPPORTED.map((h) => (
            <code key={h} className="text-xs bg-[#f1ead8] text-[#2f4a3a] px-2 py-1 rounded">{h}</code>
          ))}
        </div>
        <div className="text-xs text-[#6a6a6a]">
          Existing clients (by email) will be skipped. Unknown columns are ignored. UTF-8 encoded.
        </div>
      </div>

      <div className="rounded-2xl border-2 border-dashed border-[#c19a4b] bg-[#fbf7ee] p-8 text-center mb-6" data-testid="import-dropzone">
        <FileSpreadsheet size={36} className="text-[#8a6a3c] mx-auto mb-3" />
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => onFile(e.target.files?.[0] || null)}
          className="block mx-auto text-sm"
          data-testid="import-file-input"
        />
        {file && (
          <div className="mt-3 text-sm text-[#3a3a3a]">
            Selected: <strong>{file.name}</strong> ({Math.round(file.size / 1024)} KB)
          </div>
        )}
      </div>

      {preview.headers.length > 0 && (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 mb-6 overflow-auto">
          <div className="eyebrow text-[#8a6a3c] mb-3">Preview (first 5 rows)</div>
          <table className="text-xs w-full">
            <thead>
              <tr>
                {preview.headers.map((h, i) => (
                  <th key={i} className={`text-left py-2 px-2 ${SUPPORTED.includes(h.toLowerCase()) ? "text-[#2f4a3a] font-semibold" : "text-[#6a6a6a]"}`}>
                    {h} {SUPPORTED.includes(h.toLowerCase()) && <CheckCircle2 size={11} className="inline" />}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, i) => (
                <tr key={i} className="border-t border-[#e7dfc9]">
                  {row.map((cell, j) => <td key={j} className="py-1.5 px-2 text-[#3a3a3a]">{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Button
        onClick={upload}
        disabled={!file || submitting}
        className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] h-11"
        data-testid="import-upload-btn"
      >
        <Upload size={16} className="mr-2" />
        {submitting ? "Importing…" : "Upload & import"}
      </Button>

      {result && (
        <div className="mt-6 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5" data-testid="import-result">
          <div className="flex items-center gap-2 text-[#2f4a3a] font-semibold mb-2">
            <CheckCircle2 size={18} /> Import complete
          </div>
          <div className="text-sm space-y-1">
            <div>Imported: <strong className="text-[#2f4a3a]">{result.imported}</strong></div>
            <div>Skipped: <strong className="text-[#8a6a3c]">{result.skipped}</strong></div>
            {result.errors?.length > 0 && (
              <div className="mt-3">
                <div className="font-semibold flex items-center gap-1 text-[#7a2a2a]"><AlertCircle size={14} /> Errors (first 10)</div>
                <ul className="mt-1 text-xs text-[#5e1f1f] list-disc pl-5">
                  {result.errors.map((er, i) => <li key={i}>{er.reason}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </PortalLayout>
  );
}
