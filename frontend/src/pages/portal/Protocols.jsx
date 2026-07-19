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
import { getErrorMessage } from "../../lib/errors";
import {
  Activity, Plus, Edit3, Trash2, Send, CheckCircle2, Loader2, Clock,
  ChevronRight, Leaf, X, Search, ArchiveRestore, Archive, Upload, Sparkles,
} from "lucide-react";

const STATUS_PILL = {
  proposed: { label: "Awaiting accept", c: "bg-[#f1ead8] text-[#8a6a3c] border-[#e0d6bc]" },
  active:   { label: "Active", c: "bg-[#dde9dd] text-[#2f4a3a] border-[#a8bfa8]" },
  accepted: { label: "Accepted", c: "bg-[#dde9dd] text-[#2f4a3a] border-[#a8bfa8]" },
  completed:{ label: "Completed", c: "bg-[#3a3a3a] text-[#f6f1e6] border-[#3a3a3a]" },
  declined: { label: "Declined", c: "bg-[#f5e3e3] text-[#7a2a2a] border-[#d4a8a8]" },
  canceled: { label: "Canceled", c: "bg-[#f5e3e3] text-[#7a2a2a] border-[#d4a8a8]" },
};
function StatusPill({ status }) { const v = STATUS_PILL[status] || STATUS_PILL.proposed; return <span className={`inline-block text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border ${v.c}`}>{v.label}</span>; }

export default function Protocols() {
  const { user } = useAuth();
  const { toast } = useToast();
  const isProvider = user?.role === "practitioner" || user?.role === "admin";
  const [tab, setTab] = React.useState("enrollments");
  const [templates, setTemplates] = React.useState([]);
  const [enrollments, setEnrollments] = React.useState([]);
  const [providers, setProviders] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [statusFilter, setStatusFilter] = React.useState("all");
  const [providerFilter, setProviderFilter] = React.useState("all");
  const [clientFilter, setClientFilter] = React.useState("all");
  const [search, setSearch] = React.useState("");
  const [showInactive, setShowInactive] = React.useState(false);
  const [editingTpl, setEditingTpl] = React.useState(null);
  const [proposing, setProposing] = React.useState(null); // template being proposed
  const [openEnr, setOpenEnr] = React.useState(null); // enrollment to view sessions
  const [showAi, setShowAi] = React.useState(null); // 'transcribe' | 'generate' | null

  const loadAll = async () => {
    try {
      const [t, e, p, c] = await Promise.all([
        api.get("/protocols/templates", { params: { include_inactive: showInactive } }),
        api.get("/protocols/enrollments"),
        api.get("/practitioners").catch(() => ({ data: [] })),
        api.get("/clients").catch(() => ({ data: [] })),
      ]);
      setTemplates(t.data || []);
      setEnrollments(e.data || []);
      setProviders(p.data || []);
      setClients(c.data || []);
    } catch (e) {
      toast({ title: "Failed to load", description: getErrorMessage(e) || "" });
    }
  };
  React.useEffect(() => { loadAll(); }, [showInactive]);

  const filteredEnr = enrollments.filter((e) => {
    if (statusFilter !== "all" && e.status !== statusFilter) return false;
    if (providerFilter !== "all" && e.practitioner_id !== providerFilter) return false;
    if (clientFilter !== "all" && e.client_id !== clientFilter) return false;
    if (search && !(e.client_name || "").toLowerCase().includes(search.toLowerCase()) &&
                  !(e.template_title || "").toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const archive = async (t) => {
    try { await api.put(`/protocols/templates/${t.id}`, { ...t, active: !t.active }); toast({ title: t.active ? "Archived" : "Restored" }); loadAll(); }
    catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };
  const remove = async (t) => {
    if (!window.confirm(`Delete "${t.title}"?`)) return;
    try { await api.delete(`/protocols/templates/${t.id}`); toast({ title: "Deleted" }); loadAll(); }
    catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Protocols"
        subtitle="Detox, cleanse, and custom multi-week treatment plans."
        actions={
          isProvider && (
            <div className="flex gap-2 flex-wrap">
              <Button
                onClick={() => setShowAi("transcribe")}
                variant="outline"
                className="rounded-full h-10 border-[#c19a4b] text-[#8a6a3c] hover:bg-[#f1ead8]"
                data-testid="protocol-ai-transcribe-btn"
              >
                <Upload size={14} className="mr-2" /> AI Transcribe PDF/DOCX
              </Button>
              <Button
                onClick={() => setShowAi("generate")}
                variant="outline"
                className="rounded-full h-10 border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#f1ead8]"
                data-testid="protocol-ai-generate-btn"
              >
                <Sparkles size={14} className="mr-2" /> AI Generate
              </Button>
              <Button
                onClick={() => setEditingTpl({ title: "New protocol", description: "", weeks: 4, sessions_per_week: 2, daily_outline: "", foods_recommended: [], foods_avoid: [], supplements: [], lifestyle: "", treatment_label: "Treatment session", active: true })}
                className="rounded-full h-10 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                data-testid="protocol-new-tpl-btn"
              >
                <Plus size={14} className="mr-2" /> New protocol template
              </Button>
            </div>
          )
        }
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-[#f1ead8]">
          <TabsTrigger value="enrollments" data-testid="protocol-tab-enrollments">
            <Activity size={12} className="mr-1" /> Enrollments ({filteredEnr.length})
          </TabsTrigger>
          <TabsTrigger value="templates" data-testid="protocol-tab-templates">
            <Leaf size={12} className="mr-1" /> Templates ({templates.length})
          </TabsTrigger>
        </TabsList>

        {/* ENROLLMENTS */}
        <TabsContent value="enrollments" className="mt-5">
          <div className="flex flex-col md:flex-row gap-3 mb-5 flex-wrap">
            <div className="relative flex-1 min-w-[220px] max-w-md">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
              <Input placeholder="Search client or protocol…" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="protocol-search" />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-44 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="protocol-status-filter"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="proposed">Awaiting accept</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="declined">Declined</SelectItem>
              </SelectContent>
            </Select>
            <Select value={providerFilter} onValueChange={setProviderFilter}>
              <SelectTrigger className="w-52 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="protocol-provider-filter"><SelectValue placeholder="All providers" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All providers</SelectItem>
                {providers.map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name || p.email}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={clientFilter} onValueChange={setClientFilter}>
              <SelectTrigger className="w-52 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="protocol-client-filter"><SelectValue placeholder="All clients" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All clients</SelectItem>
                {clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {filteredEnr.length === 0 ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-12 text-center text-[#6a6a6a]">
              No active enrollments. Propose a protocol to a client from the <strong>Templates</strong> tab.
            </div>
          ) : (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="protocol-enrollments-table">
              <table className="w-full text-sm">
                <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
                  <tr>
                    <th className="text-left py-3 px-4">Proposed</th>
                    <th className="text-left py-3 px-4">Client</th>
                    <th className="text-left py-3 px-4">Protocol</th>
                    <th className="text-left py-3 px-4">Provider</th>
                    <th className="text-left py-3 px-4">Status</th>
                    <th className="text-left py-3 px-4">Progress</th>
                    <th className="text-right py-3 px-4">Open</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEnr.map((e) => {
                    const total = (e.sessions || []).length;
                    const done = (e.sessions || []).filter((s) => s.completed).length;
                    return (
                      <tr key={e.id} className="border-t border-[#e7dfc9] hover:bg-[#f1ead8]" data-testid={`protocol-enr-${e.id}`}>
                        <td className="py-3 px-4 text-xs text-[#6a6a6a] whitespace-nowrap">{new Date(e.proposed_at).toLocaleDateString([], { month: "short", day: "numeric" })}</td>
                        <td className="py-3 px-4 font-medium text-[#1f2a22]">{e.client_name}</td>
                        <td className="py-3 px-4 text-[#3a3a3a]">{e.template_title}</td>
                        <td className="py-3 px-4 text-[#3a3a3a]">{e.practitioner_name || "—"}</td>
                        <td className="py-3 px-4"><StatusPill status={e.status} /></td>
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2 text-xs text-[#3a3a3a]">
                            <div className="flex-1 max-w-[120px] h-1.5 rounded-full bg-[#e7dfc9] overflow-hidden">
                              <div className="h-full bg-[#2f4a3a]" style={{ width: total ? `${(done / total) * 100}%` : 0 }} />
                            </div>
                            {done}/{total}
                          </div>
                        </td>
                        <td className="py-3 px-4 text-right">
                          <button onClick={() => setOpenEnr(e)} className="text-[#2f4a3a] hover:underline inline-flex items-center gap-1 text-xs" data-testid={`protocol-open-${e.id}`}>
                            Open <ChevronRight size={11} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        {/* TEMPLATES */}
        <TabsContent value="templates" className="mt-5">
          <div className="flex justify-end mb-3">
            <button
              type="button"
              onClick={() => setShowInactive((v) => !v)}
              className={`h-9 px-4 text-xs uppercase tracking-widest rounded-full border transition ${
                showInactive ? "bg-[#3a3a3a] text-[#f6f1e6] border-[#3a3a3a]" : "bg-[#f6f1e6] text-[#3a3a3a] border-[#e0d6bc] hover:bg-[#f1ead8]"
              }`}
              data-testid="protocol-toggle-inactive"
            >
              {showInactive ? "Showing archived" : "Show archived"}
            </button>
          </div>
          {templates.length === 0 ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-12 text-center text-[#6a6a6a]">No protocol templates yet.</div>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5" data-testid="protocol-templates-grid">
              {templates.map((t) => (
                <div key={t.id} className={`rounded-2xl border bg-[#fbf7ee] p-5 flex flex-col ${t.active ? "border-[#e7dfc9]" : "border-[#d4c9a8] opacity-70"}`} data-testid={`protocol-tpl-${t.id}`}>
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-start gap-2 min-w-0">
                      <Leaf size={16} className="text-[#5b6f5b] mt-0.5" />
                      <h3 className="font-display text-lg text-[#1f2a22] leading-tight">{t.title}</h3>
                    </div>
                    {t.builtin ? (
                      <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#c19a4b] text-[#1f2a22] whitespace-nowrap">Built-in</span>
                    ) : !t.active ? (
                      <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#3a3a3a] text-[#f6f1e6] whitespace-nowrap">Archived</span>
                    ) : null}
                  </div>
                  <p className="text-sm text-[#5a5a5a] line-clamp-3 min-h-[3em] mb-3">{t.description || "—"}</p>
                  <div className="flex flex-wrap gap-1.5 mb-4 text-[10px] uppercase tracking-widest">
                    <span className="px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c]">{t.weeks} wk</span>
                    <span className="px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c]">{t.sessions_per_week}× / wk</span>
                    {(t.foods_recommended || []).length > 0 && <span className="px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c]">{(t.foods_recommended || []).length} ✓ foods</span>}
                  </div>
                  <div className="mt-auto flex items-center gap-3 text-sm pt-3 border-t border-[#e7dfc9]">
                    {isProvider && (
                      <button onClick={() => setProposing(t)} className="text-[#c19a4b] hover:text-[#8a6a3c] inline-flex items-center gap-1" data-testid={`protocol-propose-${t.id}`}>
                        <Send size={12} /> Propose
                      </button>
                    )}
                    {isProvider && (
                      <button onClick={() => setEditingTpl(t)} className="text-[#3a3a3a] hover:text-[#2f4a3a] inline-flex items-center gap-1" data-testid={`protocol-tpl-edit-${t.id}`}>
                        <Edit3 size={12} /> Edit
                      </button>
                    )}
                    <div className="ml-auto flex items-center gap-2">
                      <button onClick={() => archive(t)} className="text-[#6a6a6a] hover:text-[#3a3a3a]" title={t.active ? "Archive" : "Restore"} data-testid={`protocol-tpl-archive-${t.id}`}>
                        {t.active ? <Archive size={14} /> : <ArchiveRestore size={14} />}
                      </button>
                      {!t.builtin && (
                        <button onClick={() => remove(t)} className="text-[#7a2a2a] hover:opacity-70" title="Delete">
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      <ProtocolTemplateEditor template={editingTpl} onOpenChange={(v) => !v && setEditingTpl(null)} onSaved={() => { setEditingTpl(null); loadAll(); }} />
      <ProposeProtocolDialog template={proposing} clients={clients} onOpenChange={(v) => !v && setProposing(null)} onProposed={() => { setProposing(null); setTab("enrollments"); loadAll(); }} />
      <EnrollmentDialog enrollment={openEnr} onOpenChange={(v) => !v && setOpenEnr(null)} onChanged={loadAll} />
      <ProtocolAiAssistDialog
        mode={showAi}
        onOpenChange={(v) => !v && setShowAi(null)}
        onResult={(draft) => { setShowAi(null); setEditingTpl({ ...draft, active: true }); }}
      />
    </PortalLayout>
  );
}

// ---------- Template editor ----------
function ProtocolTemplateEditor({ template, onOpenChange, onSaved }) {
  const { toast } = useToast();
  const [t, setT] = React.useState(template);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => { setT(template); }, [template]);
  if (!t) return null;
  const upd = (p) => setT((prev) => ({ ...prev, ...p }));

  const save = async () => {
    if (!t.title?.trim()) { toast({ title: "Title required" }); return; }
    setSaving(true);
    try {
      const body = {
        title: t.title.trim(),
        description: t.description || "",
        weeks: parseInt(t.weeks) || 4,
        sessions_per_week: parseInt(t.sessions_per_week) || 1,
        daily_outline: t.daily_outline || "",
        foods_recommended: parseList(t.foods_recommended),
        foods_avoid: parseList(t.foods_avoid),
        supplements: t.supplements || [],
        lifestyle: t.lifestyle || "",
        treatment_label: t.treatment_label || "Session",
        active: t.active !== false,
      };
      if (t.id) await api.put(`/protocols/templates/${t.id}`, body);
      else await api.post("/protocols/templates", body);
      toast({ title: "Saved" });
      onSaved && onSaved();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={!!template} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{t.id ? "Edit protocol template" : "New protocol template"}</DialogTitle>
          <DialogDescription>Define the multi-week structure, foods, and lifestyle guidance.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid md:grid-cols-2 gap-3">
            <div><Label>Title</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.title || ""} onChange={(e) => upd({ title: e.target.value })} data-testid="protocol-tpl-title" /></div>
            <div><Label>Treatment label</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.treatment_label || ""} onChange={(e) => upd({ treatment_label: e.target.value })} placeholder="Detox treatment" /></div>
          </div>
          <div><Label>Description</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={2} value={t.description || ""} onChange={(e) => upd({ description: e.target.value })} /></div>
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <Label>Weeks</Label>
              <Input type="number" min={1} max={52} className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.weeks} onChange={(e) => upd({ weeks: parseInt(e.target.value) || 1 })} data-testid="protocol-tpl-weeks" />
            </div>
            <div>
              <Label>Sessions per week</Label>
              <Input type="number" min={1} max={14} className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.sessions_per_week} onChange={(e) => upd({ sessions_per_week: parseInt(e.target.value) || 1 })} data-testid="protocol-tpl-spw" />
            </div>
          </div>
          <div><Label>Daily outline (markdown ok)</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={5} value={t.daily_outline || ""} onChange={(e) => upd({ daily_outline: e.target.value })} /></div>
          <div className="grid md:grid-cols-2 gap-3">
            <div><Label>Recommended foods (comma-separated)</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={3} value={Array.isArray(t.foods_recommended) ? t.foods_recommended.join(", ") : (t.foods_recommended || "")} onChange={(e) => upd({ foods_recommended: e.target.value })} /></div>
            <div><Label>Foods to avoid (comma-separated)</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={3} value={Array.isArray(t.foods_avoid) ? t.foods_avoid.join(", ") : (t.foods_avoid || "")} onChange={(e) => upd({ foods_avoid: e.target.value })} /></div>
          </div>
          <div><Label>Lifestyle recommendations</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={3} value={t.lifestyle || ""} onChange={(e) => upd({ lifestyle: e.target.value })} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={saving} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="protocol-tpl-save">
            {saving ? <Loader2 size={14} className="animate-spin mr-1" /> : null} Save protocol
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
function parseList(v) {
  if (Array.isArray(v)) return v;
  if (!v) return [];
  return String(v).split(",").map((s) => s.trim()).filter(Boolean);
}

// ---------- Propose to client ----------
function ProposeProtocolDialog({ template, clients, onOpenChange, onProposed }) {
  const { toast } = useToast();
  const [clientId, setClientId] = React.useState("");
  const [weeks, setWeeks] = React.useState(template?.weeks || 4);
  const [spw, setSpw] = React.useState(template?.sessions_per_week || 1);
  const [note, setNote] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  React.useEffect(() => { if (template) { setWeeks(template.weeks); setSpw(template.sessions_per_week); setClientId(""); setNote(""); } }, [template]);
  if (!template) return null;

  const submit = async () => {
    if (!clientId) { toast({ title: "Select a client" }); return; }
    setSubmitting(true);
    try {
      await api.post("/protocols/enrollments", {
        template_id: template.id, client_id: clientId, weeks: parseInt(weeks) || template.weeks,
        sessions_per_week: parseInt(spw) || template.sessions_per_week, custom_note: note,
      });
      toast({ title: "Protocol proposed", description: "Patient will see it in their portal." });
      onProposed && onProposed();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
    finally { setSubmitting(false); }
  };

  return (
    <Dialog open={!!template} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Propose "{template.title}"</DialogTitle>
          <DialogDescription>Customize weeks/sessions for this client. They will be notified to accept.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label>Client</Label>
            <Select value={clientId} onValueChange={setClientId}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="protocol-propose-client"><SelectValue placeholder="Select client…" /></SelectTrigger>
              <SelectContent>{clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Weeks</Label><Input type="number" min={1} max={52} className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={weeks} onChange={(e) => setWeeks(e.target.value)} data-testid="protocol-propose-weeks" /></div>
            <div><Label>Sessions per week</Label><Input type="number" min={1} max={14} className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={spw} onChange={(e) => setSpw(e.target.value)} data-testid="protocol-propose-spw" /></div>
          </div>
          <div><Label>Note for the patient (optional)</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></div>
          <div className="text-xs text-[#6a6a6a]">Total sessions: <strong>{(parseInt(weeks) || 0) * (parseInt(spw) || 0)}</strong></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={submitting} className="bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22] rounded-full" data-testid="protocol-propose-submit">
            {submitting ? <Loader2 size={14} className="animate-spin mr-1" /> : <Send size={14} className="mr-1" />} Send to client
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Enrollment detail (sessions check-off) ----------
export function EnrollmentDialog({ enrollment, onOpenChange, onChanged, viewOnly }) {
  const { toast } = useToast();
  const [enr, setEnr] = React.useState(enrollment);
  React.useEffect(() => { setEnr(enrollment); }, [enrollment]);
  if (!enr) return null;
  const isInteractive = enr.status === "active" || enr.status === "accepted";
  const total = (enr.sessions || []).length;
  const done = (enr.sessions || []).filter((s) => s.completed).length;

  const toggle = async (week, session) => {
    if (viewOnly) return;
    const target = (enr.sessions || []).find((s) => s.week === week && s.session === session);
    if (!target) return;
    try {
      const r = await api.post(`/protocols/enrollments/${enr.id}/sessions`, {
        week, session, completed: !target.completed,
      });
      setEnr(r.data);
      onChanged && onChanged();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };

  const grid = {};
  (enr.sessions || []).forEach((s) => {
    if (!grid[s.week]) grid[s.week] = [];
    grid[s.week].push(s);
  });

  const snap = enr.snapshot || {};

  return (
    <Dialog open={!!enrollment} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl flex items-center gap-2">{enr.template_title} <StatusPill status={enr.status} /></DialogTitle>
          <DialogDescription>{enr.client_name} · proposed {new Date(enr.proposed_at).toLocaleDateString()}</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          {/* Progress */}
          <div className="rounded-2xl border border-[#e7dfc9] bg-[#f6f1e6] p-4">
            <div className="flex items-center justify-between text-xs text-[#3a3a3a] mb-2">
              <span><strong>{done}</strong> of <strong>{total}</strong> sessions complete</span>
              <span>{enr.weeks} wk × {enr.sessions_per_week}/wk</span>
            </div>
            <div className="h-2 rounded-full bg-[#e7dfc9] overflow-hidden">
              <div className="h-full bg-[#2f4a3a] transition-all" style={{ width: total ? `${(done / total) * 100}%` : 0 }} />
            </div>
          </div>

          {/* Session grid */}
          <div className="space-y-3">
            {Object.entries(grid).map(([week, sessions]) => (
              <div key={week} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4" data-testid={`protocol-week-${week}`}>
                <div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-2">Week {week}</div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                  {sessions.map((s) => (
                    <button
                      key={`${s.week}-${s.session}`}
                      onClick={() => toggle(s.week, s.session)}
                      disabled={!isInteractive || viewOnly}
                      className={`text-left rounded-xl border p-3 transition ${
                        s.completed
                          ? "bg-[#dde9dd] border-[#a8bfa8] text-[#1f2a22]"
                          : "bg-[#f6f1e6] border-[#e0d6bc] hover:bg-[#f1ead8] text-[#3a3a3a]"
                      } ${(!isInteractive || viewOnly) ? "opacity-60 cursor-not-allowed" : ""}`}
                      data-testid={`protocol-session-${enr.id}-w${s.week}-s${s.session}`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">Session {s.session}</span>
                        {s.completed
                          ? <CheckCircle2 size={14} className="text-[#2f4a3a]" />
                          : <Clock size={14} className="text-[#8a6a3c]" />}
                      </div>
                      <div className="text-[10px] text-[#6a6a6a] mt-1">
                        {s.completed
                          ? `Done ${s.completed_at ? new Date(s.completed_at).toLocaleDateString([], { month: "short", day: "numeric" }) : ""}`
                          : "Pending"}
                      </div>
                      {s.completed_by_name && <div className="text-[10px] text-[#8a6a3c] mt-0.5 truncate">by {s.completed_by_name}</div>}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Snapshot details */}
          {(snap.daily_outline || snap.foods_recommended?.length || snap.lifestyle) && (
            <details className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4">
              <summary className="cursor-pointer text-sm text-[#2f4a3a] font-medium">Protocol details</summary>
              <div className="mt-3 space-y-3 text-sm text-[#3a3a3a]">
                {snap.daily_outline && <div><div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-1">Daily outline</div><pre className="whitespace-pre-wrap font-body text-sm">{snap.daily_outline}</pre></div>}
                {(snap.foods_recommended || []).length > 0 && <div><div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-1">Recommended foods</div><div className="text-sm">{snap.foods_recommended.join(", ")}</div></div>}
                {(snap.foods_avoid || []).length > 0 && <div><div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-1">Foods to avoid</div><div className="text-sm">{snap.foods_avoid.join(", ")}</div></div>}
                {snap.lifestyle && <div><div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-1">Lifestyle</div><pre className="whitespace-pre-wrap font-body text-sm">{snap.lifestyle}</pre></div>}
              </div>
            </details>
          )}

          {enr.custom_note && (
            <div className="rounded-2xl border border-[#c19a4b] bg-[#f1ead8] p-4 text-sm text-[#3a3a3a]">
              <div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-1">Provider note</div>
              {enr.custom_note}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}


// ---------- AI assist (transcribe / generate) ----------
function ProtocolAiAssistDialog({ mode, onOpenChange, onResult }) {
  const { toast } = useToast();
  const [file, setFile] = React.useState(null);
  const [prompt, setPrompt] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => { if (!mode) { setFile(null); setPrompt(""); } }, [mode]);
  if (!mode) return null;

  const submit = async () => {
    setLoading(true);
    try {
      let res;
      if (mode === "transcribe") {
        if (!file) { toast({ title: "Choose a PDF, DOCX, or TXT" }); setLoading(false); return; }
        const fd = new FormData();
        fd.append("file", file);
        res = await api.post("/protocols/transcribe", fd, { headers: { "Content-Type": "multipart/form-data" } });
      } else {
        if (!prompt || prompt.length < 6) { toast({ title: "Describe what to generate" }); setLoading(false); return; }
        res = await api.post("/protocols/generate", { prompt });
      }
      const d = res.data;
      toast({
        title: "Protocol drafted",
        description: `${d.weeks} wk × ${d.sessions_per_week}/wk · ${d.foods_recommended?.length || 0} ✓ foods, ${d.foods_avoid?.length || 0} ✗ foods`,
      });
      onResult && onResult(d);
    } catch (e) {
      toast({ title: "AI failed", description: getErrorMessage(e) || "Try again." });
    } finally { setLoading(false); }
  };

  return (
    <Dialog open={!!mode} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">
            {mode === "transcribe" ? "AI Transcribe a protocol" : "AI Generate a protocol"}
          </DialogTitle>
          <DialogDescription>
            {mode === "transcribe"
              ? "Upload a PDF, DOCX, or TXT. Claude 4.5 will detect duration, frequency, foods and lifestyle."
              : "Describe the protocol you want and Claude 4.5 will draft it for you."}
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
                data-testid="protocol-ai-file-input"
              />
              {file && <div className="text-xs text-[#6a6a6a] mt-2">{file.name} · {(file.size / 1024).toFixed(1)} KB</div>}
            </div>
          ) : (
            <div>
              <Label>Describe the protocol</Label>
              <Textarea
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                rows={4}
                placeholder="e.g., 6-week liver detox with twice-weekly IV vitamin C, anti-inflammatory diet, no alcohol or caffeine."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                data-testid="protocol-ai-prompt"
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={loading} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="protocol-ai-submit">
            {loading ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Sparkles size={14} className="mr-1" />}
            {loading ? "Drafting…" : (mode === "transcribe" ? "Transcribe" : "Generate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}