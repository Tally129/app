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
import { useAuth } from "../../lib/auth";
import {
  FileText, Search, Loader2, ClipboardList, Plus, Edit3, Trash2,
  User, ChevronRight, Sparkles, Save, History as HistoryIcon, X,
} from "lucide-react";

/**
 * Phase 11 — clinic-wide SOAP Notes hub.
 *  • Notes tab: filter by client + provider; click row to open per-client chart.
 *  • Templates tab: provider/admin can manage SOAP starter templates.
 *  • New SOAP: pre-fills from a chosen template + chosen client → saves to that client.
 */
export default function SoapNotes() {
  const { user } = useAuth();
  const { toast } = useToast();
  const isProvider = user?.role === "practitioner" || user?.role === "admin";

  const [tab, setTab] = React.useState("notes");
  const [notes, setNotes] = React.useState([]);
  const [templates, setTemplates] = React.useState([]);
  const [providers, setProviders] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [providerFilter, setProviderFilter] = React.useState("all");
  const [clientFilter, setClientFilter] = React.useState("all");
  const [search, setSearch] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [editorState, setEditorState] = React.useState(null); // { client_id, template_id?, draft }
  const [tplEditor, setTplEditor] = React.useState(null); // SOAP template editor

  const loadNotes = React.useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (providerFilter !== "all") params.practitioner_id = providerFilter;
      if (search) params.search = search;
      const r = await api.get("/notes/all", { params });
      let rows = r.data || [];
      if (clientFilter !== "all") rows = rows.filter((n) => n.client_id === clientFilter);
      setNotes(rows);
    } finally { setLoading(false); }
  }, [providerFilter, clientFilter, search]);

  const loadTemplates = async () => {
    try { const r = await api.get("/soap-templates"); setTemplates(r.data || []); } catch {}
  };

  React.useEffect(() => {
    api.get("/practitioners").then((r) => setProviders(r.data || [])).catch(() => {});
    api.get("/clients").then((r) => setClients(r.data || [])).catch(() => {});
    loadTemplates();
  }, []);
  React.useEffect(() => { const t = setTimeout(loadNotes, 250); return () => clearTimeout(t); }, [loadNotes]);

  return (
    <PortalLayout>
      <PortalHeader
        title="SOAP Notes"
        subtitle="All visit notes across the clinic — filter, edit, and start new ones from templates."
        actions={
          isProvider && (
            <div className="flex gap-2 flex-wrap">
              <Button
                onClick={() => setEditorState({ client_id: "", template_id: "", draft: { subjective: "", objective: "", assessment: "", plan: "" } })}
                className="rounded-full h-10 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                data-testid="soap-new-btn"
              >
                <Plus size={14} className="mr-2" /> New SOAP note
              </Button>
            </div>
          )
        }
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-[#f1ead8]">
          <TabsTrigger value="notes" data-testid="soap-tab-notes">
            <FileText size={12} className="mr-1" /> Notes ({notes.length})
          </TabsTrigger>
          <TabsTrigger value="templates" data-testid="soap-tab-templates">
            <ClipboardList size={12} className="mr-1" /> Templates ({templates.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="notes" className="mt-5">
          <div className="flex flex-col md:flex-row gap-3 mb-5 flex-wrap">
            <div className="relative flex-1 min-w-[240px] max-w-md">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
              <Input
                placeholder="Search by client name…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9 bg-[#f6f1e6] border-[#e0d6bc]"
                data-testid="soap-search"
              />
            </div>
            <Select value={clientFilter} onValueChange={setClientFilter}>
              <SelectTrigger className="w-56 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="soap-client-filter">
                <SelectValue placeholder="All clients" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All clients</SelectItem>
                {clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={providerFilter} onValueChange={setProviderFilter}>
              <SelectTrigger className="w-56 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="soap-provider-filter">
                <SelectValue placeholder="All providers" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All providers</SelectItem>
                {providers.map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name || p.email}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="soap-notes-table">
            <table className="w-full text-sm">
              <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
                <tr>
                  <th className="text-left py-3 px-4">Date</th>
                  <th className="text-left py-3 px-4">Client</th>
                  <th className="text-left py-3 px-4">Provider</th>
                  <th className="text-left py-3 px-4">Subjective preview</th>
                  <th className="text-right py-3 px-4">Open</th>
                </tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={5} className="py-10 text-center text-[#6a6a6a]"><Loader2 className="inline animate-spin mr-2" size={14} /> Loading…</td></tr>}
                {!loading && notes.length === 0 && <tr><td colSpan={5} className="py-12 text-center text-[#6a6a6a]">No notes match. Try clearing filters or create a new note.</td></tr>}
                {!loading && notes.map((n) => (
                  <tr key={n.id} className="border-t border-[#e7dfc9] hover:bg-[#f1ead8]" data-testid={`soap-note-row-${n.id}`}>
                    <td className="py-3 px-4 text-xs text-[#6a6a6a] whitespace-nowrap">
                      {new Date(n.created_at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
                    </td>
                    <td className="py-3 px-4 font-medium text-[#1f2a22]">
                      <Link to={`/portal/provider/patients/${n.client_id}`} className="hover:underline inline-flex items-center gap-1.5">
                        <User size={12} className="text-[#8a6a3c]" /> {n.client_name || n.client_id}
                      </Link>
                    </td>
                    <td className="py-3 px-4 text-[#3a3a3a]">{n.practitioner_name || "—"}</td>
                    <td className="py-3 px-4 text-[#6a6a6a] truncate max-w-md">{(n.subjective || "").slice(0, 140) || "—"}</td>
                    <td className="py-3 px-4 text-right">
                      <Link to={`/portal/provider/patients/${n.client_id}#notes`} className="text-[#2f4a3a] hover:underline inline-flex items-center gap-1 text-xs">
                        Open chart <ChevronRight size={11} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="templates" className="mt-5">
          <div className="flex justify-end mb-4">
            {isProvider && (
              <Button
                onClick={() => setTplEditor({ title: "New template", description: "", subjective: "", objective: "", assessment: "", plan: "", visit_type: null, active: true })}
                className="rounded-full h-9 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                data-testid="soap-tpl-new-btn"
              >
                <Plus size={13} className="mr-1" /> New template
              </Button>
            )}
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="soap-templates-grid">
            {templates.map((t) => (
              <div key={t.id} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 flex flex-col" data-testid={`soap-tpl-${t.id}`}>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-start gap-2 min-w-0">
                    <ClipboardList size={16} className="text-[#8a6a3c] mt-0.5" />
                    <h3 className="font-display text-lg text-[#1f2a22] leading-tight">{t.title}</h3>
                  </div>
                  {t.visit_type && (
                    <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c] whitespace-nowrap">
                      {t.visit_type}
                    </span>
                  )}
                </div>
                <p className="text-sm text-[#5a5a5a] line-clamp-3 min-h-[3em] mb-3">{t.description || "—"}</p>
                <div className="text-xs text-[#6a6a6a] flex items-center gap-1 mb-4">
                  <Sparkles size={11} /> Pre-fills S / O / A / P sections
                </div>
                <div className="mt-auto flex items-center gap-3 text-sm pt-3 border-t border-[#e7dfc9]">
                  {isProvider && (
                    <button onClick={() => setEditorState({ client_id: "", template_id: t.id, draft: { subjective: t.subjective, objective: t.objective, assessment: t.assessment, plan: t.plan } })} className="text-[#c19a4b] hover:text-[#8a6a3c] inline-flex items-center gap-1" data-testid={`soap-use-tpl-${t.id}`}>
                      <Sparkles size={12} /> Use
                    </button>
                  )}
                  {isProvider && (
                    <button onClick={() => setTplEditor(t)} className="text-[#3a3a3a] hover:text-[#2f4a3a] inline-flex items-center gap-1" data-testid={`soap-tpl-edit-${t.id}`}>
                      <Edit3 size={12} /> Edit
                    </button>
                  )}
                </div>
              </div>
            ))}
            {templates.length === 0 && <div className="col-span-full text-sm text-[#6a6a6a] text-center py-10">No templates yet.</div>}
          </div>
        </TabsContent>
      </Tabs>

      <NoteEditorDialog
        state={editorState}
        templates={templates}
        clients={clients}
        onOpenChange={(v) => !v && setEditorState(null)}
        onSaved={() => { setEditorState(null); loadNotes(); }}
      />
      <TemplateEditorDialog
        template={tplEditor}
        onOpenChange={(v) => !v && setTplEditor(null)}
        onSaved={() => { setTplEditor(null); loadTemplates(); }}
      />
    </PortalLayout>
  );
}

// ---------- New / edit SOAP note dialog ----------
function NoteEditorDialog({ state, templates, clients, onOpenChange, onSaved }) {
  const { toast } = useToast();
  const [draft, setDraft] = React.useState(null);
  const [clientId, setClientId] = React.useState("");
  const [templateId, setTemplateId] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (state) {
      setDraft(state.draft);
      setClientId(state.client_id || "");
      setTemplateId(state.template_id || "");
    }
  }, [state]);
  if (!state || !draft) return null;

  const applyTemplate = (tplId) => {
    setTemplateId(tplId);
    if (!tplId || tplId === "blank") return;
    const t = templates.find((x) => x.id === tplId);
    if (!t) return;
    setDraft({ subjective: t.subjective || "", objective: t.objective || "", assessment: t.assessment || "", plan: t.plan || "" });
  };

  const save = async () => {
    if (!clientId) { toast({ title: "Select a client" }); return; }
    setSaving(true);
    try {
      await api.post("/notes", { client_id: clientId, ...draft });
      toast({ title: "SOAP note saved", description: "Visible in the patient chart." });
      onSaved && onSaved();
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={!!state} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">New SOAP note</DialogTitle>
          <DialogDescription>Choose a client and (optionally) a template, then edit the SOAP sections.</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <Label>Client</Label>
              <Select value={clientId} onValueChange={setClientId}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="soap-editor-client"><SelectValue placeholder="Select client…" /></SelectTrigger>
                <SelectContent>{clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label>Template</Label>
              <Select value={templateId || "blank"} onValueChange={applyTemplate}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="soap-editor-template"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="blank">Blank</SelectItem>
                  {templates.map((t) => <SelectItem key={t.id} value={t.id}>{t.title}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <SoapSection label="Subjective" value={draft.subjective} onChange={(v) => setDraft({ ...draft, subjective: v })} testid="soap-s" />
          <SoapSection label="Objective" value={draft.objective} onChange={(v) => setDraft({ ...draft, objective: v })} testid="soap-o" />
          <SoapSection label="Assessment" value={draft.assessment} onChange={(v) => setDraft({ ...draft, assessment: v })} testid="soap-a" />
          <SoapSection label="Plan" value={draft.plan} onChange={(v) => setDraft({ ...draft, plan: v })} testid="soap-p" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={saving} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="soap-editor-save">
            {saving ? <Loader2 size={14} className="animate-spin mr-1" /> : <Save size={14} className="mr-1" />} Save note
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
function SoapSection({ label, value, onChange, testid }) {
  return (
    <div>
      <Label>{label}</Label>
      <Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={4} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={testid} />
    </div>
  );
}

// ---------- SOAP template editor ----------
function TemplateEditorDialog({ template, onOpenChange, onSaved }) {
  const { toast } = useToast();
  const [t, setT] = React.useState(template);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => { setT(template); }, [template]);
  if (!t) return null;

  const upd = (patch) => setT((prev) => ({ ...prev, ...patch }));
  const save = async () => {
    if (!t.title?.trim()) { toast({ title: "Title required" }); return; }
    setSaving(true);
    try {
      const body = {
        title: t.title.trim(),
        description: t.description || "",
        subjective: t.subjective || "",
        objective: t.objective || "",
        assessment: t.assessment || "",
        plan: t.plan || "",
        visit_type: t.visit_type || null,
        active: t.active !== false,
      };
      if (t.id) await api.put(`/soap-templates/${t.id}`, body);
      else await api.post("/soap-templates", body);
      toast({ title: "Template saved" });
      onSaved && onSaved();
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={!!template} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{t.id ? "Edit SOAP template" : "New SOAP template"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <Label>Title</Label>
              <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.title || ""} onChange={(e) => upd({ title: e.target.value })} data-testid="soap-tpl-editor-title" />
            </div>
            <div>
              <Label>Visit type</Label>
              <Select value={t.visit_type || "any"} onValueChange={(v) => upd({ visit_type: v === "any" ? null : v })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Any visit</SelectItem>
                  <SelectItem value="telehealth">Telehealth</SelectItem>
                  <SelectItem value="in_person">In-person</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label>Description</Label>
            <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.description || ""} onChange={(e) => upd({ description: e.target.value })} />
          </div>
          <SoapSection label="Subjective" value={t.subjective} onChange={(v) => upd({ subjective: v })} testid="tpl-s" />
          <SoapSection label="Objective" value={t.objective} onChange={(v) => upd({ objective: v })} testid="tpl-o" />
          <SoapSection label="Assessment" value={t.assessment} onChange={(v) => upd({ assessment: v })} testid="tpl-a" />
          <SoapSection label="Plan" value={t.plan} onChange={(v) => upd({ plan: v })} testid="tpl-p" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={saving} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="soap-tpl-editor-save">
            {saving ? <Loader2 size={14} className="animate-spin mr-1" /> : <Save size={14} className="mr-1" />} Save template
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
