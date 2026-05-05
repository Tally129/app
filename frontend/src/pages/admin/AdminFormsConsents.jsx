import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import {
  FileText, Sparkles, Upload, Plus, Send, Edit3, Eye, Trash2,
  Search, Archive, ArchiveRestore, Loader2, Copy, X, GripVertical, CheckCircle2, ExternalLink,
} from "lucide-react";

const FIELD_TYPES = [
  { v: "text", label: "Short text" },
  { v: "textarea", label: "Long text" },
  { v: "email", label: "Email" },
  { v: "phone", label: "Phone" },
  { v: "number", label: "Number" },
  { v: "date", label: "Date" },
  { v: "checkbox", label: "Checkbox (yes/no)" },
  { v: "radio", label: "Single choice" },
  { v: "select", label: "Dropdown" },
  { v: "signature", label: "Signature" },
];

const CATEGORIES = [
  { v: "consent", label: "Consent" },
  { v: "treatment", label: "Treatment" },
  { v: "intake", label: "Intake" },
  { v: "hipaa", label: "HIPAA" },
  { v: "photo_release", label: "Photo Release" },
  { v: "other", label: "Other" },
];

const CAT_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.v, c.label]));

export default function AdminFormsConsents() {
  const { toast } = useToast();
  const [tab, setTab] = React.useState("templates");
  const [templates, setTemplates] = React.useState([]);
  const [submissions, setSubmissions] = React.useState([]);
  const [includeInactive, setIncludeInactive] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [categoryFilter, setCategoryFilter] = React.useState("all");
  const [editing, setEditing] = React.useState(null); // template object or null
  const [showEditor, setShowEditor] = React.useState(false);
  const [showAi, setShowAi] = React.useState(null); // 'transcribe' | 'generate' | null
  const [showSend, setShowSend] = React.useState(null); // template object
  const [previewing, setPreviewing] = React.useState(null);

  const load = async () => {
    try {
      const [t, s] = await Promise.all([
        api.get("/forms/templates", { params: { include_inactive: includeInactive } }),
        api.get("/forms/submissions"),
      ]);
      setTemplates(t.data || []);
      setSubmissions(s.data || []);
    } catch (e) {
      toast({ title: "Failed to load", description: e?.response?.data?.detail || "" });
    }
  };
  React.useEffect(() => { load(); }, [includeInactive]);

  const filteredTpls = templates.filter((t) => {
    if (categoryFilter !== "all" && t.category !== categoryFilter) return false;
    if (search && !(t.title || "").toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const startBlank = () => {
    setEditing({
      title: "Untitled form",
      description: "",
      category: "consent",
      fields: [
        { id: "patient-name", type: "text", label: "Patient name", required: true, options: [] },
        { id: "signature", type: "signature", label: "Patient signature", required: true, options: [] },
      ],
      active: true,
    });
    setShowEditor(true);
  };

  const startFromAi = (tpl) => { setEditing({ ...tpl, active: true }); setShowEditor(true); setShowAi(null); };

  const archive = async (t) => {
    try {
      await api.put(`/forms/templates/${t.id}`, { ...t, active: !t.active });
      toast({ title: t.active ? "Archived" : "Unarchived" });
      load();
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
  };
  const remove = async (t) => {
    if (!window.confirm(`Delete "${t.title}"? This cannot be undone.`)) return;
    try { await api.delete(`/forms/templates/${t.id}`); toast({ title: "Deleted" }); load(); }
    catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
  };

  return (
    <PortalLayout>
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-8">
        <div>
          <h1 className="font-display text-[34px] md:text-[42px] text-[#1f2a22] leading-tight" data-testid="page-title">
            Forms &amp; Consents
          </h1>
          <p className="text-[#6a6a6a] mt-1 max-w-xl">
            Manage HIPAA, consent, and intake forms. Upload a legacy PDF or DOCX and let AI transcribe it into an editable digital form.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => setShowAi("transcribe")}
            variant="outline"
            className="rounded-full h-10 border-[#c19a4b] text-[#8a6a3c] hover:bg-[#f1ead8]"
            data-testid="forms-ai-transcribe-btn"
          >
            <Upload size={14} className="mr-2" /> AI Transcribe PDF/DOCX
          </Button>
          <Button
            onClick={() => setShowAi("generate")}
            className="rounded-full h-10 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
            data-testid="forms-ai-generate-btn"
          >
            <Sparkles size={14} className="mr-2" /> AI Generate
          </Button>
          <Button
            onClick={startBlank}
            variant="outline"
            className="rounded-full h-10 border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#f1ead8]"
            data-testid="forms-blank-btn"
          >
            <Plus size={14} className="mr-2" /> Blank form
          </Button>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-[#f1ead8]">
          <TabsTrigger value="templates" data-testid="forms-tab-templates">
            Templates ({filteredTpls.length})
          </TabsTrigger>
          <TabsTrigger value="submissions" data-testid="forms-tab-submissions">
            Submissions ({submissions.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="templates" className="mt-5">
          <div className="flex flex-col md:flex-row gap-3 mb-5">
            <div className="relative flex-1 max-w-md">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
              <Input
                placeholder="Search templates…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9 bg-[#f6f1e6] border-[#e0d6bc]"
                data-testid="forms-search"
              />
            </div>
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="w-44 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="forms-category-filter">
                <SelectValue placeholder="All categories" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All categories</SelectItem>
                {CATEGORIES.map((c) => <SelectItem key={c.v} value={c.v}>{c.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <button
              type="button"
              onClick={() => setIncludeInactive((v) => !v)}
              className={`h-10 px-4 text-xs uppercase tracking-widest rounded-full border transition ${
                includeInactive ? "bg-[#3a3a3a] text-[#f6f1e6] border-[#3a3a3a]" : "bg-[#f6f1e6] text-[#3a3a3a] border-[#e0d6bc] hover:bg-[#f1ead8]"
              }`}
              data-testid="forms-toggle-inactive"
            >
              {includeInactive ? "Showing archived" : "Show archived"}
            </button>
          </div>

          {filteredTpls.length === 0 ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-16 text-center text-[#6a6a6a]">
              <FileText size={28} className="mx-auto text-[#c19a4b] mb-3" />
              No templates match. Try clearing filters or upload a legacy form to AI-transcribe.
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5" data-testid="forms-templates-grid">
              {filteredTpls.map((t) => (
                <TemplateCard
                  key={t.id}
                  t={t}
                  onEdit={() => { setEditing(t); setShowEditor(true); }}
                  onPreview={() => setPreviewing(t)}
                  onSend={() => setShowSend(t)}
                  onArchive={() => archive(t)}
                  onDelete={() => remove(t)}
                />
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="submissions" className="mt-5">
          <SubmissionsList rows={submissions} onReload={load} />
        </TabsContent>
      </Tabs>

      <FormEditorDialog
        open={showEditor}
        onOpenChange={(v) => { setShowEditor(v); if (!v) setEditing(null); }}
        template={editing}
        onSaved={() => { setShowEditor(false); setEditing(null); load(); }}
      />
      <AiAssistDialog
        mode={showAi}
        onOpenChange={(v) => !v && setShowAi(null)}
        onResult={startFromAi}
      />
      <SendFormDialog
        template={showSend}
        onOpenChange={(v) => !v && setShowSend(null)}
        onSent={() => { setShowSend(null); load(); setTab("submissions"); }}
      />
      <PreviewDialog template={previewing} onOpenChange={(v) => !v && setPreviewing(null)} />
    </PortalLayout>
  );
}

// ---------- Template card ----------
function TemplateCard({ t, onEdit, onPreview, onSend, onArchive, onDelete }) {
  const fcount = (t.fields || []).length;
  const hasSig = (t.fields || []).some((f) => f.type === "signature");
  return (
    <div className={`rounded-2xl border bg-[#fbf7ee] p-5 flex flex-col ${t.active ? "border-[#e7dfc9]" : "border-[#d4c9a8] opacity-70"}`} data-testid={`forms-tpl-${t.id}`}>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-start gap-2 flex-1 min-w-0">
          <FileText size={18} className="text-[#8a6a3c] mt-0.5" />
          <h3 className="font-display text-lg text-[#1f2a22] leading-tight">{t.title}</h3>
        </div>
        {t.builtin ? (
          <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#c19a4b] text-[#1f2a22] whitespace-nowrap">
            Built-in
          </span>
        ) : !t.active ? (
          <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#3a3a3a] text-[#f6f1e6] whitespace-nowrap">
            Archived
          </span>
        ) : null}
      </div>
      <p className="text-sm text-[#5a5a5a] line-clamp-3 min-h-[3em] mb-4">{t.description || "—"}</p>
      <div className="flex flex-wrap gap-1.5 mb-4 text-[10px] uppercase tracking-widest">
        <span className="px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c]">{CAT_LABEL[t.category] || t.category}</span>
        <span className="px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c]">{fcount} fields</span>
        {hasSig && <span className="px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c]">Signature</span>}
      </div>
      <div className="mt-auto pt-3 border-t border-[#e7dfc9] flex items-center gap-3 text-sm">
        <button onClick={onEdit} className="text-[#3a3a3a] hover:text-[#2f4a3a] inline-flex items-center gap-1 transition" data-testid={`forms-tpl-edit-${t.id}`}>
          <Edit3 size={13} /> Edit
        </button>
        <button onClick={onPreview} className="text-[#3a3a3a] hover:text-[#2f4a3a] inline-flex items-center gap-1 transition" data-testid={`forms-tpl-preview-${t.id}`}>
          <Eye size={13} /> Preview
        </button>
        <button onClick={onSend} className="text-[#c19a4b] hover:text-[#8a6a3c] inline-flex items-center gap-1 transition" data-testid={`forms-tpl-send-${t.id}`}>
          <Send size={13} /> Send
        </button>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={onArchive} className="text-[#6a6a6a] hover:text-[#3a3a3a] transition" title={t.active ? "Archive" : "Unarchive"} data-testid={`forms-tpl-archive-${t.id}`}>
            {t.active ? <Archive size={14} /> : <ArchiveRestore size={14} />}
          </button>
          {!t.builtin && (
            <button onClick={onDelete} className="text-[#7a2a2a] hover:opacity-70 transition" title="Delete" data-testid={`forms-tpl-delete-${t.id}`}>
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- Submissions ----------
function SubmissionsList({ rows, onReload }) {
  const { toast } = useToast();
  const copyLink = (s) => {
    const url = `${window.location.origin}${s.submit_url}`;
    navigator.clipboard.writeText(url);
    toast({ title: "Link copied", description: url });
  };
  if ((rows || []).length === 0) {
    return (
      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-12 text-center text-[#6a6a6a]">
        No forms have been sent yet. Use the <strong>Send</strong> button on any template.
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="forms-submissions-table">
      <table className="w-full text-sm">
        <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
          <tr>
            <th className="text-left py-3 px-4">Sent</th>
            <th className="text-left py-3 px-4">Form</th>
            <th className="text-left py-3 px-4">Recipient</th>
            <th className="text-left py-3 px-4">Status</th>
            <th className="text-left py-3 px-4">Submitted</th>
            <th className="text-right py-3 px-4">Link</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} className="border-t border-[#e7dfc9]" data-testid={`forms-sub-${s.id}`}>
              <td className="py-3 px-4 text-xs text-[#6a6a6a]">{new Date(s.created_at).toLocaleDateString([], { month: "short", day: "numeric" })}</td>
              <td className="py-3 px-4 font-medium text-[#1f2a22]">{s.template_title || s.template_id}</td>
              <td className="py-3 px-4 text-[#3a3a3a]">{s.client_name || <span className="text-[#8a6a3c] italic">unlinked</span>}</td>
              <td className="py-3 px-4">
                <StatusPill status={s.status} />
              </td>
              <td className="py-3 px-4 text-xs text-[#6a6a6a]">
                {s.submitted_at ? new Date(s.submitted_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—"}
              </td>
              <td className="py-3 px-4 text-right">
                {s.status === "sent" && s.submit_url && (
                  <button onClick={() => copyLink(s)} className="inline-flex items-center gap-1 text-xs text-[#2f4a3a] hover:underline" data-testid={`forms-copy-link-${s.id}`}>
                    <Copy size={11} /> Copy
                  </button>
                )}
                {s.status === "submitted" && (
                  <span className="inline-flex items-center gap-1 text-xs text-[#5b6f5b]">
                    <CheckCircle2 size={11} /> Done
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function StatusPill({ status }) {
  const map = {
    sent:      { label: "Awaiting", c: "bg-[#f1ead8] text-[#8a6a3c] border-[#e0d6bc]" },
    submitted: { label: "Submitted", c: "bg-[#dde9dd] text-[#2f4a3a] border-[#a8bfa8]" },
    expired:   { label: "Expired", c: "bg-[#f5e3e3] text-[#7a2a2a] border-[#d4a8a8]" },
    void:      { label: "Voided", c: "bg-[#3a3a3a] text-[#f6f1e6] border-[#3a3a3a]" },
  };
  const v = map[status] || map.sent;
  return <span className={`inline-block text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border ${v.c}`}>{v.label}</span>;
}

// ---------- Editor dialog ----------
function FormEditorDialog({ open, onOpenChange, template, onSaved }) {
  const { toast } = useToast();
  const [t, setT] = React.useState(template);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => { setT(template); }, [template]);
  if (!t) return null;

  const update = (patch) => setT((prev) => ({ ...prev, ...patch }));
  const updField = (idx, patch) => setT((prev) => {
    const fields = [...(prev.fields || [])];
    fields[idx] = { ...fields[idx], ...patch };
    return { ...prev, fields };
  });
  const addField = () => setT((prev) => ({
    ...prev,
    fields: [...(prev.fields || []), { id: `field-${(prev.fields || []).length + 1}`, type: "text", label: "New question", required: false, options: [] }],
  }));
  const removeField = (idx) => setT((prev) => ({ ...prev, fields: prev.fields.filter((_, i) => i !== idx) }));
  const moveField = (idx, dir) => setT((prev) => {
    const fields = [...prev.fields];
    const j = idx + dir;
    if (j < 0 || j >= fields.length) return prev;
    [fields[idx], fields[j]] = [fields[j], fields[idx]];
    return { ...prev, fields };
  });

  const save = async () => {
    if (!t.title?.trim()) { toast({ title: "Title is required" }); return; }
    setSaving(true);
    try {
      const body = {
        title: t.title.trim(),
        description: t.description || "",
        category: t.category || "other",
        active: t.active !== false,
        fields: (t.fields || []).map((f, i) => ({
          id: f.id || `field-${i + 1}`,
          type: f.type || "text",
          label: f.label || `Field ${i + 1}`,
          required: !!f.required,
          placeholder: f.placeholder || null,
          options: Array.isArray(f.options) ? f.options : (f.options || "").split(",").map((s) => s.trim()).filter(Boolean),
          help_text: f.help_text || null,
        })),
      };
      if (t.id) await api.put(`/forms/templates/${t.id}`, body);
      else await api.post("/forms/templates", body);
      toast({ title: "Saved" });
      onSaved && onSaved();
    } catch (e) {
      toast({ title: "Save failed", description: e?.response?.data?.detail || "" });
    } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{t.id ? "Edit form" : "New form"}</DialogTitle>
          <DialogDescription>Build the questions your patients will fill in.</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <Label>Title</Label>
              <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.title || ""} onChange={(e) => update({ title: e.target.value })} data-testid="form-editor-title" />
            </div>
            <div>
              <Label>Category</Label>
              <Select value={t.category || "consent"} onValueChange={(v) => update({ category: v })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="form-editor-category"><SelectValue /></SelectTrigger>
                <SelectContent>{CATEGORIES.map((c) => <SelectItem key={c.v} value={c.v}>{c.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label>Description</Label>
            <Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={2} value={t.description || ""} onChange={(e) => update({ description: e.target.value })} data-testid="form-editor-description" />
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label>Fields ({(t.fields || []).length})</Label>
              <Button size="sm" variant="outline" onClick={addField} className="rounded-full" data-testid="form-editor-add-field">
                <Plus size={12} className="mr-1" /> Add field
              </Button>
            </div>
            <div className="space-y-3">
              {(t.fields || []).map((f, idx) => (
                <div key={idx} className="rounded-xl border border-[#e7dfc9] bg-[#f6f1e6] p-3" data-testid={`form-editor-field-${idx}`}>
                  <div className="flex items-start gap-2">
                    <div className="flex flex-col gap-1 pt-1">
                      <button onClick={() => moveField(idx, -1)} className="text-[#8a6a3c] hover:text-[#3a3a3a] text-xs" title="Up">▲</button>
                      <button onClick={() => moveField(idx, 1)} className="text-[#8a6a3c] hover:text-[#3a3a3a] text-xs" title="Down">▼</button>
                    </div>
                    <div className="flex-1 space-y-2">
                      <div className="grid md:grid-cols-[1fr_180px] gap-2">
                        <Input placeholder="Question label" value={f.label || ""} onChange={(e) => updField(idx, { label: e.target.value })} className="bg-[#fbf7ee] border-[#e0d6bc]" />
                        <Select value={f.type} onValueChange={(v) => updField(idx, { type: v })}>
                          <SelectTrigger className="bg-[#fbf7ee] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
                          <SelectContent>{FIELD_TYPES.map((x) => <SelectItem key={x.v} value={x.v}>{x.label}</SelectItem>)}</SelectContent>
                        </Select>
                      </div>
                      {(f.type === "radio" || f.type === "select") && (
                        <Input
                          placeholder="Comma-separated options"
                          value={Array.isArray(f.options) ? f.options.join(", ") : (f.options || "")}
                          onChange={(e) => updField(idx, { options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                          className="bg-[#fbf7ee] border-[#e0d6bc]"
                        />
                      )}
                      <div className="flex items-center gap-4 text-xs text-[#3a3a3a]">
                        <label className="inline-flex items-center gap-1.5">
                          <input type="checkbox" checked={!!f.required} onChange={(e) => updField(idx, { required: e.target.checked })} />
                          Required
                        </label>
                        {f.help_text !== undefined && (
                          <Input
                            placeholder="Helper text (optional)"
                            value={f.help_text || ""}
                            onChange={(e) => updField(idx, { help_text: e.target.value })}
                            className="flex-1 h-8 bg-[#fbf7ee] border-[#e0d6bc] text-xs"
                          />
                        )}
                      </div>
                    </div>
                    <button onClick={() => removeField(idx)} className="text-[#7a2a2a] hover:opacity-70 mt-1" title="Remove">
                      <X size={14} />
                    </button>
                  </div>
                </div>
              ))}
              {(t.fields || []).length === 0 && (
                <div className="text-sm text-[#6a6a6a] py-6 text-center border border-dashed border-[#e0d6bc] rounded-xl">No fields yet — click <strong>Add field</strong>.</div>
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={saving} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="form-editor-save">
            {saving ? <Loader2 size={14} className="mr-1 animate-spin" /> : null} Save form
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- AI assist dialog ----------
function AiAssistDialog({ mode, onOpenChange, onResult }) {
  const { toast } = useToast();
  const [file, setFile] = React.useState(null);
  const [category, setCategory] = React.useState("");
  const [prompt, setPrompt] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => { if (!mode) { setFile(null); setPrompt(""); setCategory(""); } }, [mode]);
  if (!mode) return null;

  const submit = async () => {
    setLoading(true);
    try {
      let res;
      if (mode === "transcribe") {
        if (!file) { toast({ title: "Choose a PDF, DOCX, or TXT" }); setLoading(false); return; }
        const fd = new FormData();
        fd.append("file", file);
        if (category) fd.append("category", category);
        res = await api.post("/forms/transcribe", fd, { headers: { "Content-Type": "multipart/form-data" } });
      } else {
        if (!prompt || prompt.length < 6) { toast({ title: "Describe what to generate" }); setLoading(false); return; }
        res = await api.post("/forms/generate", { prompt, category: category || "other" });
      }
      toast({ title: "Form ready", description: `${(res.data.fields || []).length} fields detected.` });
      onResult && onResult({ ...res.data });
    } catch (e) {
      toast({ title: "AI failed", description: e?.response?.data?.detail || "Try again." });
    } finally { setLoading(false); }
  };

  return (
    <Dialog open={!!mode} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">
            {mode === "transcribe" ? "AI Transcribe a form" : "AI Generate a form"}
          </DialogTitle>
          <DialogDescription>
            {mode === "transcribe"
              ? "Upload a PDF or DOCX. Claude 4.5 will extract the questions and rebuild it as an editable digital form."
              : "Describe the form you want and Claude 4.5 will draft it for you."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {mode === "transcribe" ? (
            <div>
              <Label>File</Label>
              <input
                type="file"
                accept=".pdf,.docx,.txt"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="mt-2 w-full text-sm file:mr-3 file:rounded-full file:border-0 file:bg-[#2f4a3a] file:text-[#f6f1e6] file:px-4 file:py-2 file:cursor-pointer"
                data-testid="forms-ai-file-input"
              />
              {file && <div className="text-xs text-[#6a6a6a] mt-2">{file.name} · {(file.size / 1024).toFixed(1)} KB</div>}
            </div>
          ) : (
            <div>
              <Label>Describe the form</Label>
              <Textarea
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                rows={4}
                placeholder="e.g., Wellness intake for new patients with allergies, medications, primary concerns, and a signature."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                data-testid="forms-ai-prompt"
              />
            </div>
          )}
          <div>
            <Label>Category hint (optional)</Label>
            <Select value={category || "auto"} onValueChange={(v) => setCategory(v === "auto" ? "" : v)}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="forms-ai-category"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto-detect</SelectItem>
                {CATEGORIES.map((c) => <SelectItem key={c.v} value={c.v}>{c.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={loading} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="forms-ai-submit">
            {loading ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Sparkles size={14} className="mr-1" />}
            {loading ? "Working…" : (mode === "transcribe" ? "Transcribe" : "Generate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Send dialog ----------
function SendFormDialog({ template, onOpenChange, onSent }) {
  const { toast } = useToast();
  const [clients, setClients] = React.useState([]);
  const [clientId, setClientId] = React.useState("none");
  const [hours, setHours] = React.useState(168);
  const [submitting, setSubmitting] = React.useState(false);
  const [resultUrl, setResultUrl] = React.useState("");

  React.useEffect(() => {
    if (!template) { setResultUrl(""); setClientId("none"); return; }
    api.get("/clients").then((r) => setClients(r.data || [])).catch(() => {});
  }, [template]);
  if (!template) return null;

  const submit = async () => {
    setSubmitting(true);
    try {
      const body = {
        template_id: template.id,
        expires_in_hours: parseInt(hours) || 168,
      };
      if (clientId && clientId !== "none") body.client_id = clientId;
      const r = await api.post("/forms/send", body);
      const url = `${window.location.origin}${r.data.submit_url}`;
      setResultUrl(url);
      try { await navigator.clipboard.writeText(url); } catch {}
      toast({ title: "Form link generated", description: "Copied to clipboard." });
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    } finally { setSubmitting(false); }
  };

  return (
    <Dialog open={!!template} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Send "{template.title}"</DialogTitle>
          <DialogDescription>Generates a tokenized soft-link the patient can open without signing in.</DialogDescription>
        </DialogHeader>
        {!resultUrl ? (
          <div className="space-y-4">
            <div>
              <Label>Client (optional)</Label>
              <Select value={clientId} onValueChange={setClientId}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="forms-send-client"><SelectValue placeholder="Unlinked link" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">No client (unlinked link)</SelectItem>
                  {clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}
                </SelectContent>
              </Select>
              <p className="text-xs text-[#6a6a6a] mt-2">Linking lets the form attach to the patient's chart on submit.</p>
            </div>
            <div>
              <Label>Link expires in (hours)</Label>
              <Input type="number" min={1} max={720} className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={hours} onChange={(e) => setHours(e.target.value)} data-testid="forms-send-hours" />
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="rounded-2xl border border-[#a8bfa8] bg-[#dde9dd] p-4">
              <div className="flex items-center gap-2 text-[#2f4a3a] text-sm font-medium"><CheckCircle2 size={14} /> Link ready</div>
              <code className="block mt-3 text-xs break-all text-[#1f2a22] bg-[#fbf7ee] rounded p-2 border border-[#e7dfc9]">{resultUrl}</code>
              <a href={resultUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-[#2f4a3a] mt-2 hover:underline">
                <ExternalLink size={11} /> Open in new tab
              </a>
            </div>
            <p className="text-xs text-[#6a6a6a]">SMS/email sending integration is on the roadmap. For now, copy this link and share it with the patient.</p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => { onOpenChange(false); resultUrl && onSent && onSent(); }}>{resultUrl ? "Done" : "Cancel"}</Button>
          {!resultUrl && (
            <Button onClick={submit} disabled={submitting} className="bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22] rounded-full" data-testid="forms-send-submit">
              {submitting ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Send size={14} className="mr-1" />} Generate link
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Preview dialog ----------
function PreviewDialog({ template, onOpenChange }) {
  if (!template) return null;
  return (
    <Dialog open={!!template} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-2xl max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{template.title}</DialogTitle>
          <DialogDescription>{template.description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {(template.fields || []).map((f) => (
            <div key={f.id} className="space-y-1">
              <Label>{f.label}{f.required && <span className="text-[#7a2a2a]"> *</span>}</Label>
              <FieldRenderer field={f} preview />
              {f.help_text && <p className="text-xs text-[#6a6a6a]">{f.help_text}</p>}
            </div>
          ))}
          {(template.fields || []).length === 0 && <p className="text-sm text-[#6a6a6a]">No fields configured yet.</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Shared field renderer (also used by FormResponder if imported)
export function FieldRenderer({ field, value, onChange, preview }) {
  const common = "bg-[#f6f1e6] border-[#e0d6bc]";
  const f = field;
  if (preview && !onChange) onChange = () => {};
  if (f.type === "textarea") return <Textarea className={common} rows={3} value={value || ""} placeholder={f.placeholder || ""} onChange={(e) => onChange(e.target.value)} disabled={preview} />;
  if (f.type === "date") return <Input type="date" className={common} value={value || ""} onChange={(e) => onChange(e.target.value)} disabled={preview} />;
  if (f.type === "email") return <Input type="email" className={common} value={value || ""} placeholder={f.placeholder || ""} onChange={(e) => onChange(e.target.value)} disabled={preview} />;
  if (f.type === "phone") return <Input type="tel" className={common} value={value || ""} placeholder={f.placeholder || ""} onChange={(e) => onChange(e.target.value)} disabled={preview} />;
  if (f.type === "number") return <Input type="number" className={common} value={value || ""} placeholder={f.placeholder || ""} onChange={(e) => onChange(e.target.value)} disabled={preview} />;
  if (f.type === "checkbox") return (
    <label className="inline-flex items-center gap-2 text-sm text-[#3a3a3a]">
      <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} disabled={preview} /> Yes, I confirm
    </label>
  );
  if (f.type === "radio") return (
    <div className="space-y-1.5">
      {(f.options || []).map((opt) => (
        <label key={opt} className="flex items-center gap-2 text-sm text-[#3a3a3a]">
          <input type="radio" name={f.id} checked={value === opt} onChange={() => onChange(opt)} disabled={preview} /> {opt}
        </label>
      ))}
    </div>
  );
  if (f.type === "select") return (
    <select className={`${common} w-full rounded-md h-10 px-3 text-sm`} value={value || ""} onChange={(e) => onChange(e.target.value)} disabled={preview}>
      <option value="">Select…</option>
      {(f.options || []).map((opt) => <option key={opt} value={opt}>{opt}</option>)}
    </select>
  );
  if (f.type === "signature") return <SignaturePad value={value} onChange={onChange} disabled={preview} />;
  return <Input type="text" className={common} value={value || ""} placeholder={f.placeholder || ""} onChange={(e) => onChange(e.target.value)} disabled={preview} />;
}

// Lightweight signature pad
export function SignaturePad({ value, onChange, disabled }) {
  const ref = React.useRef(null);
  const drawing = React.useRef(false);
  const [empty, setEmpty] = React.useState(!value);

  React.useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#fbf7ee";
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.strokeStyle = "#1f2a22";
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    if (value) {
      const img = new Image();
      img.onload = () => ctx.drawImage(img, 0, 0, c.width, c.height);
      img.src = value;
      setEmpty(false);
    }
  }, [value]);

  const point = (e) => {
    const c = ref.current;
    const rect = c.getBoundingClientRect();
    const t = e.touches ? e.touches[0] : e;
    return [(t.clientX - rect.left) * (c.width / rect.width), (t.clientY - rect.top) * (c.height / rect.height)];
  };
  const down = (e) => { if (disabled) return; drawing.current = true; const [x, y] = point(e); const ctx = ref.current.getContext("2d"); ctx.beginPath(); ctx.moveTo(x, y); };
  const move = (e) => { if (!drawing.current || disabled) return; e.preventDefault(); const [x, y] = point(e); const ctx = ref.current.getContext("2d"); ctx.lineTo(x, y); ctx.stroke(); setEmpty(false); };
  const up = () => { if (!drawing.current) return; drawing.current = false; if (onChange) onChange(ref.current.toDataURL("image/png")); };
  const clear = () => {
    const c = ref.current;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#fbf7ee"; ctx.fillRect(0, 0, c.width, c.height);
    setEmpty(true);
    if (onChange) onChange(null);
  };

  return (
    <div className="space-y-2">
      <canvas
        ref={ref}
        width={500}
        height={140}
        className="w-full rounded-xl border-2 border-dashed border-[#c19a4b] touch-none cursor-crosshair"
        onMouseDown={down} onMouseMove={move} onMouseUp={up} onMouseLeave={up}
        onTouchStart={down} onTouchMove={move} onTouchEnd={up}
        data-testid="signature-canvas"
      />
      {!disabled && (
        <button type="button" onClick={clear} className="text-xs text-[#7a2a2a] hover:underline" data-testid="signature-clear">
          Clear signature
        </button>
      )}
      {empty && !disabled && <p className="text-xs text-[#8a6a3c] italic">Sign above with your mouse or finger.</p>}
    </div>
  );
}
