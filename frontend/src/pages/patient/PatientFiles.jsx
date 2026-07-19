import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api, { API_BASE, LS } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Upload, Download, FolderOpen } from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";

export default function PatientFiles({ clientIdProp }) {
  const { toast } = useToast();
  const [files, setFiles] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [uploading, setUploading] = React.useState(false);
  const [clientId, setClientId] = React.useState(clientIdProp || null);
  const inputRef = React.useRef(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      let cid = clientIdProp || clientId;
      if (!cid) {
        const me = await api.get("/clients/me");
        cid = me.data.id;
        setClientId(cid);
      }
      const r = await api.get("/files", { params: { client_id: cid } });
      setFiles(r.data || []);
    } catch (e) {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [clientId, clientIdProp]);

  React.useEffect(() => {
    load();
  }, [load]);

  const onPick = () => inputRef.current?.click();
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("category", "lab");
      if (clientId) fd.append("client_id", clientId);
      await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast({ title: "Uploaded", description: file.name });
      e.target.value = "";
      load();
    } catch (err) {
      toast({ title: "Upload failed", description: getErrorMessage(err) || "Try again." });
    } finally {
      setUploading(false);
    }
  };

  const download = async (f) => {
    const token = localStorage.getItem(LS.access);
    const res = await fetch(`${API_BASE}/files/${f.id}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      toast({ title: "Download failed" });
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = f.filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Files & Labs"
        subtitle="Encrypted storage. Only you and your care team can access."
        actions={
          <Button onClick={onPick} disabled={uploading} className="btn-lift h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
            <Upload size={16} className="mr-2" /> {uploading ? "Uploading…" : "Upload"}
          </Button>
        }
      />
      <input ref={inputRef} type="file" onChange={onFile} className="hidden" />

      {loading ? (
        <div className="text-[#6a6a6a]">Loading…</div>
      ) : files.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <FolderOpen size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No files yet. Upload labs or documents to share with your care team.</div>
        </div>
      ) : (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
              <tr>
                <th className="text-left py-3 px-4">File</th>
                <th className="text-left py-3 px-4">Category</th>
                <th className="text-left py-3 px-4">Uploaded</th>
                <th className="text-left py-3 px-4">By</th>
                <th className="text-right py-3 px-4">Action</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.id} className="border-t border-[#e7dfc9]">
                  <td className="py-3 px-4 text-[#2a2a2a]">{f.filename}</td>
                  <td className="py-3 px-4 text-[#6a6a6a] capitalize">{f.category}</td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{new Date(f.created_at).toLocaleDateString()}</td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{f.uploaded_by_name || "—"}</td>
                  <td className="py-3 px-4 text-right">
                    <Button size="sm" variant="outline" onClick={() => download(f)} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#2f4a3a] hover:text-[#f6f1e6]">
                      <Download size={14} className="mr-1" /> Download
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PortalLayout>
  );
}