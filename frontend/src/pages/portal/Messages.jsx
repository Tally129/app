import React from "react";
import { useParams } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { MessageSquare, Plus, Send, FileText, Paperclip } from "lucide-react";
import { useAuth } from "../../lib/auth";

export default function Messages() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [threads, setThreads] = React.useState([]);
  const [active, setActive] = React.useState(null);
  const [messages, setMessages] = React.useState([]);
  const [body, setBody] = React.useState("");
  const [templates, setTemplates] = React.useState([]);
  const [newOpen, setNewOpen] = React.useState(false);
  const [participants, setParticipants] = React.useState([]);
  const [newForm, setNewForm] = React.useState({ participant_id: "", subject: "", first_message: "" });
  const fileRef = React.useRef(null);
  const [uploading, setUploading] = React.useState(false);
  const [attachments, setAttachments] = React.useState([]);

  const loadThreads = React.useCallback(() => api.get("/messages/threads").then((r) => setThreads(r.data || [])), []);

  React.useEffect(() => {
    loadThreads();
    api.get("/messages/templates").then((r) => setTemplates(r.data.templates || []));
    if (user?.role === "client") {
      api.get("/practitioners").then((r) => setParticipants(r.data || []));
    } else {
      api.get("/clients").then((r) => setParticipants(r.data || []));
    }
  }, [loadThreads, user?.role]);

  React.useEffect(() => {
    if (!active) return;
    api.get(`/messages/threads/${active.id}`).then((r) => setMessages(r.data || []));
    loadThreads();
  }, [active, loadThreads]);

  const send = async () => {
    if (!body.trim() && attachments.length === 0) return;
    try {
      await api.post(`/messages/threads/${active.id}/messages`, {
        body: body.trim(),
        attachment_file_ids: attachments.map((a) => a.id),
      });
      setBody("");
      setAttachments([]);
      const r = await api.get(`/messages/threads/${active.id}`);
      setMessages(r.data || []);
      loadThreads();
    } catch (e) { toast({ title: "Failed" }); }
  };

  const createThread = async () => {
    if (!newForm.participant_id || !newForm.subject) return toast({ title: "Fill all fields" });
    try {
      const { data } = await api.post("/messages/threads", newForm);
      setNewOpen(false);
      setNewForm({ participant_id: "", subject: "", first_message: "" });
      await loadThreads();
      setActive(data);
    } catch (e) { toast({ title: "Failed" }); }
  };

  const uploadAttachment = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("category", "doc");
      if (active?.client_id) fd.append("client_id", active.client_id);
      const { data } = await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setAttachments((a) => [...a, { id: data.id, filename: data.filename }]);
      e.target.value = "";
    } catch { toast({ title: "Upload failed" }); }
    finally { setUploading(false); }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Messages"
        subtitle="Secure, PHI-free notes between you and your care team."
        actions={<Button onClick={() => setNewOpen(true)} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"><Plus size={14} className="mr-2" /> New message</Button>}
      />

      <div className="grid md:grid-cols-[320px_1fr] gap-4 h-[calc(100vh-280px)] min-h-[480px]">
        {/* Thread list */}
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-y-auto">
          {threads.length === 0 ? (
            <div className="p-6 text-sm text-[#6a6a6a] text-center">
              <MessageSquare size={24} className="mx-auto text-[#c19a4b] mb-2" />
              No conversations yet.
            </div>
          ) : (
            threads.map((t) => (
              <button
                key={t.id}
                onClick={() => setActive(t)}
                className={`w-full text-left px-4 py-3 border-b border-[#e7dfc9] hover:bg-[#f1ead8]/50 ${active?.id === t.id ? "bg-[#f1ead8]" : ""}`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium text-[#1f2a22] text-sm truncate">
                    {user?.role === "client" ? t.practitioner_name : t.client_name}
                  </div>
                  {t.unread_for_me > 0 && (
                    <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-[#c19a4b] text-[#1f2a22] text-[10px] font-semibold">{t.unread_for_me}</span>
                  )}
                </div>
                <div className="text-xs text-[#8a6a3c] mt-0.5 truncate">{t.subject}</div>
                <div className="text-xs text-[#6a6a6a] mt-1 truncate">{t.last_message_preview || "—"}</div>
              </button>
            ))
          )}
        </div>

        {/* Thread view */}
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] flex flex-col">
          {!active ? (
            <div className="flex-1 flex items-center justify-center text-[#6a6a6a] text-sm">Select a conversation or start a new one.</div>
          ) : (
            <>
              <div className="px-5 py-3 border-b border-[#e7dfc9]">
                <div className="font-display text-lg text-[#1f2a22]">{active.subject}</div>
                <div className="text-xs text-[#6a6a6a]">with {user?.role === "client" ? active.practitioner_name : active.client_name}</div>
              </div>
              <div className="flex-1 overflow-y-auto p-5 space-y-3">
                {messages.map((m) => {
                  const mine = m.sender_id === user?.id;
                  return (
                    <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${mine ? "bg-[#2f4a3a] text-[#f6f1e6]" : "bg-[#f1ead8] text-[#2a2a2a]"}`}>
                        <div className="whitespace-pre-wrap">{m.body}</div>
                        {m.attachment_file_ids?.length > 0 && (
                          <div className="mt-2 space-y-1">
                            {m.attachment_file_ids.map((fid) => (
                              <div key={fid} className={`text-xs inline-flex items-center gap-1 ${mine ? "text-[#d7b878]" : "text-[#8a6a3c]"}`}>
                                <FileText size={12} /> Attached file
                              </div>
                            ))}
                          </div>
                        )}
                        <div className={`text-[10px] mt-1 ${mine ? "text-[#d7b878]" : "text-[#8a6a3c]"}`}>
                          {new Date(m.created_at).toLocaleString([], { hour: "numeric", minute: "2-digit", month: "short", day: "numeric" })}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="border-t border-[#e7dfc9] p-4 space-y-2">
                {templates.length > 0 && user?.role !== "client" && (
                  <div className="flex flex-wrap gap-1">
                    {templates.map((t) => (
                      <button key={t.id} onClick={() => setBody((b) => (b ? b + "\n\n" : "") + t.body)} className="text-[11px] rounded-full border border-[#e0d6bc] bg-[#f6f1e6] px-3 py-1 hover:border-[#c19a4b]">
                        {t.label}
                      </button>
                    ))}
                  </div>
                )}
                {attachments.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {attachments.map((a) => (
                      <div key={a.id} className="text-xs inline-flex items-center gap-2 bg-[#f1ead8] rounded-full px-3 py-1">
                        <Paperclip size={12} /> {a.filename}
                        <button onClick={() => setAttachments((x) => x.filter((i) => i.id !== a.id))} className="text-[#7a2a2a]">×</button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex gap-2 items-end">
                  <Textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Type a message…" className="bg-[#f6f1e6] border-[#e0d6bc] min-h-[64px] flex-1" />
                  <input type="file" ref={fileRef} className="hidden" onChange={uploadAttachment} />
                  <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={uploading} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6] h-11">
                    <Paperclip size={16} />
                  </Button>
                  <Button onClick={send} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] h-11"><Send size={16} /></Button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <Dialog open={newOpen} onOpenChange={setNewOpen}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader><DialogTitle className="font-display text-2xl">New conversation</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>{user?.role === "client" ? "Practitioner" : "Patient"}</Label>
              <Select value={newForm.participant_id} onValueChange={(v) => setNewForm({ ...newForm, participant_id: v })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue placeholder="Choose" /></SelectTrigger>
                <SelectContent>{participants.map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name || p.email}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Subject</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={newForm.subject} onChange={(e) => setNewForm({ ...newForm, subject: e.target.value })} placeholder="e.g. Follow-up question" /></div>
            <div><Label>Message</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] min-h-[80px]" value={newForm.first_message} onChange={(e) => setNewForm({ ...newForm, first_message: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewOpen(false)}>Cancel</Button>
            <Button onClick={createThread} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">Send</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
