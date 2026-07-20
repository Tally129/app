import React from "react";
import { useParams, Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api, { API_BASE, LS } from "../../lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { ChevronLeft, PlusCircle, Save, Upload, Download, FolderOpen, DollarSign } from "lucide-react";
import TreatmentPlanBuilder from "../../components/TreatmentPlanBuilder";
import LabsPanel from "../../components/LabsPanel";
import SymptomTrends from "../../components/SymptomTrends";
import { AuthorizationBadge, useDelegatedEdit } from "../../components/AuthorizationBadge";
import { useAuth } from "../../lib/auth";
import { getErrorMessage } from "../../lib/errors";

export default function PatientChart() {
  const { id } = useParams();
  const { toast } = useToast();
  const { user } = useAuth();
  const role = user?.role;
  const isProvider = role === "practitioner";
  const { canEdit, state: authState, delegation } = useDelegatedEdit({
    role, clientId: id, recordStatus: "draft",
  });
  const [client, setClient] = React.useState(null);
  const [intake, setIntake] = React.useState(null);
  const [notes, setNotes] = React.useState([]);
  const [files, setFiles] = React.useState([]);
  const [amending, setAmending] = React.useState({});
  const [showNew, setShowNew] = React.useState(false);
  const [newNote, setNewNote] = React.useState({ subjective: "", objective: "", assessment: "", plan: "" });
  const [uploading, setUploading] = React.useState(false);
  const fileRef = React.useRef(null);

  const loadAll = React.useCallback(async () => {
    const c = await api.get(`/clients/${id}`);
    setClient(c.data);
    const i = await api.get(`/intake/${id}`);
    setIntake(i.data);
    const n = await api.get("/notes", { params: { client_id: id } });
    setNotes(n.data || []);
    const f = await api.get("/files", { params: { client_id: id } });
    setFiles(f.data || []);
  }, [id]);

  React.useEffect(() => { loadAll(); }, [loadAll]);

  const createNote = async () => {
    try {
      await api.post("/notes", { client_id: id, ...newNote });
      toast({ title: "Note saved" });
      setNewNote({ subjective: "", objective: "", assessment: "", plan: "" });
      setShowNew(false);
      loadAll();
    } catch (e) {
      toast({ title: "Failed", description: getErrorMessage(e) || "Try again." });
    }
  };

  const addAmendment = async (noteId) => {
    const content = amending[noteId];
    if (!content) return;
    try {
      await api.post(`/notes/${noteId}/amend`, { content });
      setAmending({ ...amending, [noteId]: "" });
      loadAll();
      toast({ title: "Amendment added" });
    } catch (e) {
      toast({ title: "Failed" });
    }
  };

  const onPickFile = () => fileRef.current?.click();
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("category", "lab");
      fd.append("client_id", id);
      await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast({ title: "Uploaded" });
      e.target.value = "";
      loadAll();
    } catch (err) {
      toast({ title: "Upload failed", description: getErrorMessage(err) || "Try again." });
    } finally {
      setUploading(false);
    }
  };

  const downloadFile = async (f) => {
    const token = localStorage.getItem(LS.access);
    const res = await fetch(`${API_BASE}/files/${f.id}/download`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return toast({ title: "Download failed" });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = f.filename; a.click(); URL.revokeObjectURL(url);
  };

  if (!client)
    return (
      <PortalLayout><div className="text-[#6a6a6a]">Loading…</div></PortalLayout>
    );

  return (
    <PortalLayout>
      <Link to="/portal/provider/patients" className="inline-flex items-center gap-2 text-sm text-[#6a6a6a] hover:text-[#2f4a3a] mb-4">
        <ChevronLeft size={16} /> Back to patients
      </Link>
      <PortalHeader
        title={client.full_name || "Patient"}
        subtitle={`${client.email || ""} · ${client.phone || ""}`}
      />

      <Tabs defaultValue="summary" className="w-full">
        <TabsList className="bg-[#f1ead8] p-1 rounded-full flex-wrap h-auto">
          <TabsTrigger value="summary" className="rounded-full px-4">Summary</TabsTrigger>
          <TabsTrigger value="intake" className="rounded-full px-4">Intake</TabsTrigger>
          <TabsTrigger value="notes" className="rounded-full px-4">SOAP Notes</TabsTrigger>
          <TabsTrigger value="plan" className="rounded-full px-4">Treatment Plan</TabsTrigger>
          <TabsTrigger value="labs" className="rounded-full px-4">Labs</TabsTrigger>
          <TabsTrigger value="symptoms" className="rounded-full px-4">Symptoms</TabsTrigger>
          <TabsTrigger value="files" className="rounded-full px-4">Files</TabsTrigger>
          <TabsTrigger value="billing" className="rounded-full px-4">Billing</TabsTrigger>
        </TabsList>

        <TabsContent value="summary" className="mt-6">
          <div className="grid md:grid-cols-3 gap-4">
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow text-[#8a6a3c]">Demographics</div>
              <dl className="mt-3 text-sm space-y-1 text-[#3a3a3a]">
                <div><span className="text-[#6a6a6a]">DOB:</span> {client.dob || intake?.demographics?.dob || "—"}</div>
                <div><span className="text-[#6a6a6a]">Sex:</span> {client.sex || intake?.demographics?.sex || "—"}</div>
                <div><span className="text-[#6a6a6a]">Address:</span> {client.address || intake?.demographics?.address || "—"}</div>
                <div><span className="text-[#6a6a6a]">Emergency:</span> {client.emergency_contact || intake?.demographics?.emergency_contact || "—"}</div>
              </dl>
            </div>
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow text-[#8a6a3c]">Recent notes</div>
              <div className="mt-3 text-2xl font-display text-[#1f2a22]">{notes.length}</div>
              <Link to="#" onClick={(e) => { e.preventDefault(); document.querySelector('[value="notes"]')?.click(); }} className="text-sm text-[#2f4a3a] hover:underline">View all</Link>
            </div>
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow text-[#8a6a3c]">Files on chart</div>
              <div className="mt-3 text-2xl font-display text-[#1f2a22]">{files.length}</div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="intake" className="mt-6">
          {!intake ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-8 text-[#6a6a6a]">No intake submitted yet.</div>
          ) : (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 space-y-5 text-sm">
              <IntakeSection title="Demographics" data={intake.demographics} />
              <IntakeSection title="Health history" data={intake.health_history} />
              <IntakeSection title="Symptoms" data={intake.symptoms} />
              <IntakeSection title="Lifestyle" data={intake.lifestyle} />
              <IntakeSection title="Consent" data={intake.consent} />
              {intake.completed_at && (
                <div className="text-xs text-[#6a6a6a]">Completed {new Date(intake.completed_at).toLocaleString()}</div>
              )}
            </div>
          )}
        </TabsContent>

        <TabsContent value="notes" className="mt-6 space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <AuthorizationBadge state={authState} data-testid="notes-auth-badge" />
            <Button
              onClick={() => setShowNew((v) => !v)}
              disabled={!canEdit}
              title={canEdit ? "" : "Provider authorization required"}
              className="btn-lift h-10 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="notes-new-btn"
            >
              <PlusCircle size={16} className="mr-2" /> New SOAP note
            </Button>
          </div>

          {showNew && (
            <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf7ee] p-5 space-y-3">
              <SoapInput label="Subjective" value={newNote.subjective} onChange={(v) => setNewNote({ ...newNote, subjective: v })} />
              <SoapInput label="Objective" value={newNote.objective} onChange={(v) => setNewNote({ ...newNote, objective: v })} />
              <SoapInput label="Assessment" value={newNote.assessment} onChange={(v) => setNewNote({ ...newNote, assessment: v })} />
              <SoapInput label="Plan" value={newNote.plan} onChange={(v) => setNewNote({ ...newNote, plan: v })} />
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setShowNew(false)} className="rounded-full">Cancel</Button>
                <Button onClick={createNote} className="btn-lift rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">
                  <Save size={16} className="mr-2" /> Save note
                </Button>
              </div>
            </div>
          )}

          {notes.length === 0 && <div className="text-[#6a6a6a] text-sm">No notes yet.</div>}

          {notes.map((n) => (
            <article key={n.id} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6">
              <header className="flex flex-col md:flex-row md:items-center md:justify-between mb-3">
                <div className="text-xs tracking-widest uppercase text-[#8a6a3c]">{new Date(n.created_at).toLocaleString()}</div>
                <div className="text-sm text-[#3a3a3a]">By {n.practitioner_name || "Practitioner"}</div>
              </header>
              <SoapDisplay label="Subjective" value={n.subjective} />
              <SoapDisplay label="Objective" value={n.objective} />
              <SoapDisplay label="Assessment" value={n.assessment} />
              <SoapDisplay label="Plan" value={n.plan} />

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

              <div className="mt-4 flex gap-2">
                <Input
                  value={amending[n.id] || ""}
                  onChange={(e) => setAmending({ ...amending, [n.id]: e.target.value })}
                  placeholder={isProvider ? "Add amendment (original note stays immutable)" : "Only the assigned provider may amend"}
                  disabled={!isProvider}
                  className="bg-[#f6f1e6] border-[#e0d6bc] disabled:opacity-60"
                  data-testid={`amend-input-${n.id}`}
                />
                <Button
                  onClick={() => addAmendment(n.id)}
                  disabled={!isProvider || !amending[n.id]}
                  title={isProvider ? "" : "Only the assigned provider may amend"}
                  className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] disabled:opacity-40 disabled:cursor-not-allowed"
                  data-testid={`amend-btn-${n.id}`}
                >
                  Amend
                </Button>
              </div>
            </article>
          ))}
        </TabsContent>

        <TabsContent value="plan" className="mt-6">
          <TreatmentPlanBuilder clientId={id} />
        </TabsContent>

        <TabsContent value="labs" className="mt-6">
          <LabsPanel clientId={id} />
        </TabsContent>

        <TabsContent value="symptoms" className="mt-6">
          <SymptomTrends clientId={id} />
        </TabsContent>

        <TabsContent value="files" className="mt-6">
          <div className="flex justify-end mb-3">
            <Button onClick={onPickFile} disabled={uploading} className="btn-lift h-10 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
              <Upload size={16} className="mr-2" /> {uploading ? "Uploading…" : "Upload"}
            </Button>
            <input type="file" ref={fileRef} onChange={onFile} className="hidden" />
          </div>
          {files.length === 0 ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
              <FolderOpen size={28} className="mx-auto text-[#c19a4b]" />
              <div className="mt-3">No files yet.</div>
            </div>
          ) : (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
                  <tr>
                    <th className="text-left py-3 px-4">File</th>
                    <th className="text-left py-3 px-4">Category</th>
                    <th className="text-left py-3 px-4">Uploaded</th>
                    <th className="text-right py-3 px-4">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((f) => (
                    <tr key={f.id} className="border-t border-[#e7dfc9]">
                      <td className="py-3 px-4">{f.filename}</td>
                      <td className="py-3 px-4 capitalize text-[#6a6a6a]">{f.category}</td>
                      <td className="py-3 px-4 text-[#6a6a6a]">{new Date(f.created_at).toLocaleDateString()}</td>
                      <td className="py-3 px-4 text-right">
                        <Button size="sm" variant="outline" onClick={() => downloadFile(f)} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#2f4a3a] hover:text-[#f6f1e6]">
                          <Download size={14} className="mr-1" /> Download
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="billing" className="mt-6">
          <PatientBillingTab clientId={id} />
        </TabsContent>

      </Tabs>
    </PortalLayout>
  );
}

function SoapInput({ label, value, onChange }) {
  return (
    <div>
      <Label className="text-[11px] uppercase tracking-widest text-[#8a6a3c]">{label}</Label>
      <Textarea value={value} onChange={(e) => onChange(e.target.value)} className="mt-1 bg-[#f6f1e6] border-[#e0d6bc] min-h-[80px]" />
    </div>
  );
}

function SoapDisplay({ label, value }) {
  if (!value) return null;
  return (
    <div className="mb-3">
      <div className="text-[11px] uppercase tracking-widest text-[#8a6a3c]">{label}</div>
      <div className="text-[14px] text-[#2a2a2a] whitespace-pre-wrap leading-relaxed">{value}</div>
    </div>
  );
}

function IntakeSection({ title, data }) {
  if (!data || Object.keys(data).length === 0) return null;
  return (
    <div>
      <div className="eyebrow text-[#8a6a3c]">{title}</div>
      <dl className="mt-2 grid sm:grid-cols-2 gap-x-6 gap-y-1">
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className="text-[#3a3a3a]">
            <span className="text-[#6a6a6a] capitalize">{k.replace(/_/g, " ")}:</span>{" "}
            {typeof v === "boolean" ? (v ? "Yes" : "No") : String(v || "—")}
          </div>
        ))}
      </dl>
    </div>
  );
}

function PatientBillingTab({ clientId }) {
  const { toast } = useToast();
  const [invoices, setInvoices] = React.useState([]);
  const [form, setForm] = React.useState({ description: "", amount: "" });

  const load = React.useCallback(() => {
    api.get("/invoices", { params: { client_id: clientId } }).then((r) => setInvoices(r.data || []));
  }, [clientId]);
  React.useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!form.description || !form.amount) return toast({ title: "Add description & amount" });
    try {
      await api.post("/invoices", {
        client_id: clientId,
        description: form.description,
        amount: Number(form.amount),
      });
      toast({ title: "Invoice created" });
      setForm({ description: "", amount: "" });
      load();
    } catch (e) { toast({ title: "Failed" }); }
  };

  const markPaid = async (inv) => {
    const ref = window.prompt("Chase POS terminal reference (optional):", "");
    try {
      await api.post(`/invoices/${inv.id}/mark-paid`, { method: "chase_pos_manual", external_ref: ref || null });
      toast({ title: "Marked paid" });
      load();
    } catch { toast({ title: "Failed" }); }
  };

  return (
    <div>
      <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf7ee] p-5 mb-5 grid md:grid-cols-4 gap-3">
        <div className="md:col-span-2">
          <Label>Description</Label>
          <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" placeholder="e.g. IV Drip + consult" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </div>
        <div>
          <Label>Amount (USD)</Label>
          <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="number" step="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
        </div>
        <div className="flex items-end">
          <Button onClick={create} className="w-full rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
            <DollarSign size={14} className="mr-1" /> Add invoice
          </Button>
        </div>
      </div>

      {invoices.length === 0 ? (
        <div className="text-sm text-[#6a6a6a]">No invoices yet.</div>
      ) : (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
              <tr>
                <th className="text-left py-3 px-4">Date</th>
                <th className="text-left py-3 px-4">Description</th>
                <th className="text-right py-3 px-4">Amount</th>
                <th className="text-left py-3 px-4">Status</th>
                <th className="text-right py-3 px-4">Action</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((i) => (
                <tr key={i.id} className="border-t border-[#e7dfc9]">
                  <td className="py-3 px-4 text-[#6a6a6a]">{new Date(i.created_at).toLocaleDateString()}</td>
                  <td className="py-3 px-4">{i.description}</td>
                  <td className="py-3 px-4 text-right">${i.amount.toFixed(2)}</td>
                  <td className="py-3 px-4">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${i.status === "paid" ? "bg-[#e7dfc9] text-[#2f4a3a]" : "bg-[#fbf2d9] text-[#6b4a1c]"}`}>{i.status}</span>
                    {i.payment_method && <span className="ml-2 text-[10px] text-[#6a6a6a]">({i.payment_method.replace("_", " ")})</span>}
                  </td>
                  <td className="py-3 px-4 text-right">
                    {i.status !== "paid" && (
                      <Button size="sm" variant="outline" onClick={() => markPaid(i)} className="rounded-full border-[#c19a4b] text-[#8a6a3c] hover:bg-[#c19a4b] hover:text-[#1f2a22]">
                        Mark paid (Chase POS)
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
