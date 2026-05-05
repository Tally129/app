import React from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import api, { API_BASE, LS } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Checkbox } from "../components/ui/checkbox";
import { useToast } from "../hooks/use-toast";
import {
  Video, Mic, MicOff, VideoOff, PhoneOff, ArrowLeft,
  ShieldCheck, AlertCircle, Loader2, CheckCircle2, MonitorUp,
  MessageSquare, Send, Circle, Square,
} from "lucide-react";

/**
 * Self-hosted WebRTC telehealth visit.
 *
 * Stages:
 *   loading → consent (clients only) → tech → in-call → ended
 *
 * Architecture:
 *  - WebSocket signaling at /api/ws/visit/{appt_id}?token=...
 *  - 1:1 peer connection using browser RTCPeerConnection
 *  - Provider issues the SDP offer once both peers are present.
 *  - Public STUN servers for NAT traversal.
 *  - In-call: chat sidebar (relayed via WS), screen share, recording (MediaRecorder → /visits/{id}/recording).
 */
const ICE_SERVERS = [
  { urls: "stun:stun.l.google.com:19302" },
  { urls: "stun:stun1.l.google.com:19302" },
];

export default function TelehealthVisit() {
  const { id } = useParams();
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [appt, setAppt] = React.useState(null);
  const [stage, setStage] = React.useState("loading");
  const [errMsg, setErrMsg] = React.useState("");
  const [consent, setConsent] = React.useState({ acknowledged: false, signature: "" });

  const [localStream, setLocalStream] = React.useState(null);
  const [micOn, setMicOn] = React.useState(true);
  const [camOn, setCamOn] = React.useState(true);
  const [sharing, setSharing] = React.useState(false);
  const [peerOnline, setPeerOnline] = React.useState(false);
  const [chatMsgs, setChatMsgs] = React.useState([]);
  const [chatDraft, setChatDraft] = React.useState("");
  const [chatOpen, setChatOpen] = React.useState(false);
  const [recording, setRecording] = React.useState(false);

  const localVideoRef = React.useRef(null);
  const remoteVideoRef = React.useRef(null);
  const wsRef = React.useRef(null);
  const pcRef = React.useRef(null);
  const localStreamRef = React.useRef(null); // mirror for cleanup
  const recorderRef = React.useRef(null);
  const recChunksRef = React.useRef([]);

  const isProvider = user?.role && user.role !== "client";
  const role = isProvider ? "provider" : "client";

  // 1) Load appointment
  React.useEffect(() => {
    const run = async () => {
      try {
        const r = await api.get("/appointments");
        const mine = (r.data || []).find((a) => a.id === id);
        if (!mine) { setErrMsg("Visit not found."); setStage("error"); return; }
        setAppt(mine);
        if (!isProvider && !mine.consent_telehealth) setStage("consent");
        else setStage("tech");
      } catch (e) {
        setErrMsg(e?.response?.data?.detail || "Could not load visit."); setStage("error");
      }
    };
    run();
  }, [id, isProvider]);

  // 2) Camera/mic preview during tech stage
  React.useEffect(() => {
    if (stage !== "tech" || localStream) return;
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        setLocalStream(s);
        localStreamRef.current = s;
        if (localVideoRef.current) localVideoRef.current.srcObject = s;
      } catch (e) {
        toast({ title: "Camera/mic blocked", description: "Allow access in your browser to continue." });
      }
    })();
    // eslint-disable-next-line
  }, [stage]);

  // Cleanup on unmount
  React.useEffect(() => {
    return () => endCall(false);
    // eslint-disable-next-line
  }, []);

  // ---------- consent ----------
  const submitConsent = async () => {
    if (!consent.acknowledged || !consent.signature.trim()) {
      toast({ title: "Acknowledge and type your name to consent." }); return;
    }
    try {
      await api.post(`/appointments/${id}/telehealth/consent`, { signature: consent.signature.trim() });
      toast({ title: "Consent recorded" });
      const r = await api.get("/appointments");
      const mine = (r.data || []).find((a) => a.id === id);
      setAppt(mine);
      setStage("tech");
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
  };

  // ---------- WebRTC + signaling ----------
  const sendWS = (obj) => { if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(obj)); };

  const newPC = (signalingStream) => {
    const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    pc.onicecandidate = (e) => { if (e.candidate) sendWS({ type: "ice-candidate", candidate: e.candidate }); };
    pc.ontrack = (e) => {
      if (remoteVideoRef.current && remoteVideoRef.current.srcObject !== e.streams[0]) {
        remoteVideoRef.current.srcObject = e.streams[0];
      }
    };
    pc.onconnectionstatechange = () => {
      if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
        setPeerOnline(false);
      }
    };
    if (signalingStream) {
      signalingStream.getTracks().forEach((t) => pc.addTrack(t, signalingStream));
    }
    return pc;
  };

  const startCall = async () => {
    if (!localStream) { toast({ title: "Allow camera & mic first" }); return; }
    setStage("in-call");
    // Open WS
    const token = localStorage.getItem(LS.access);
    const wsUrl = API_BASE.replace(/^http/, "ws") + `/ws/visit/${id}?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // load chat history
      api.get(`/visits/${id}/chat`).then((r) => {
        setChatMsgs((r.data || []).map((m) => ({ from: m.from_role, body: m.body, ts: m.ts })));
      }).catch(() => {});
    };

    pcRef.current = newPC(localStream);

    ws.onmessage = async (ev) => {
      let data; try { data = JSON.parse(ev.data); } catch { return; }
      const pc = pcRef.current;

      if (data.type === "joined") {
        setPeerOnline(!!data.peer_present);
        if (isProvider && data.peer_present) {
          // Provider initiates the offer
          await createOffer();
        }
      } else if (data.type === "peer-joined") {
        setPeerOnline(true);
        toast({ title: "Other party joined" });
        if (isProvider) await createOffer();
      } else if (data.type === "peer-left") {
        setPeerOnline(false);
        toast({ title: "Other party disconnected" });
      } else if (data.type === "webrtc-offer") {
        await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        sendWS({ type: "webrtc-answer", sdp: answer });
      } else if (data.type === "webrtc-answer") {
        await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
      } else if (data.type === "ice-candidate") {
        try { await pc.addIceCandidate(data.candidate); } catch (e) { console.warn("ice add", e); }
      } else if (data.type === "chat") {
        setChatMsgs((m) => [...m, { from: data.from, body: data.body, ts: new Date().toISOString() }]);
      }
    };

    ws.onerror = (e) => console.warn("WS error", e);
    ws.onclose = () => { /* peer-left will fire from server when it disconnects */ };
  };

  const createOffer = async () => {
    const pc = pcRef.current; if (!pc) return;
    const offer = await pc.createOffer({ offerToReceiveVideo: true, offerToReceiveAudio: true });
    await pc.setLocalDescription(offer);
    sendWS({ type: "webrtc-offer", sdp: offer });
  };

  const toggleMic = () => {
    if (!localStream) return;
    localStream.getAudioTracks().forEach((t) => (t.enabled = !micOn));
    setMicOn((v) => !v);
    sendWS({ type: "media-state", mic: !micOn, cam: camOn });
  };
  const toggleCam = () => {
    if (!localStream) return;
    localStream.getVideoTracks().forEach((t) => (t.enabled = !camOn));
    setCamOn((v) => !v);
    sendWS({ type: "media-state", mic: micOn, cam: !camOn });
  };

  const toggleScreenShare = async () => {
    const pc = pcRef.current; if (!pc) return;
    if (!sharing) {
      try {
        const screen = await navigator.mediaDevices.getDisplayMedia({ video: true });
        const screenTrack = screen.getVideoTracks()[0];
        const sender = pc.getSenders().find((s) => s.track && s.track.kind === "video");
        if (sender) await sender.replaceTrack(screenTrack);
        screenTrack.onended = () => toggleScreenShare();
        setSharing(true);
        sendWS({ type: "screen-share", on: true });
      } catch (e) { toast({ title: "Screen share denied" }); }
    } else {
      const camTrack = localStream.getVideoTracks()[0];
      const sender = pc.getSenders().find((s) => s.track && s.track.kind === "video");
      if (sender && camTrack) await sender.replaceTrack(camTrack);
      setSharing(false);
      sendWS({ type: "screen-share", on: false });
    }
  };

  const sendChat = () => {
    const body = chatDraft.trim(); if (!body) return;
    setChatMsgs((m) => [...m, { from: role, body, ts: new Date().toISOString() }]);
    sendWS({ type: "chat", body });
    setChatDraft("");
  };

  // ---------- recording ----------
  const startRecording = () => {
    if (!localStream || recording) return;
    try {
      // Composite stream of local + remote audio/video tracks
      const composite = new MediaStream();
      localStream.getTracks().forEach((t) => composite.addTrack(t));
      const remote = remoteVideoRef.current?.srcObject;
      if (remote) remote.getTracks().forEach((t) => composite.addTrack(t));
      const mr = new MediaRecorder(composite, { mimeType: "video/webm;codecs=vp8,opus" });
      recorderRef.current = mr;
      recChunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) recChunksRef.current.push(e.data); };
      mr.onstop = async () => {
        const blob = new Blob(recChunksRef.current, { type: "video/webm" });
        const fd = new FormData();
        fd.append("file", blob, `visit-${id}.webm`);
        try {
          await api.post(`/visits/${id}/recording`, fd, { headers: { "Content-Type": "multipart/form-data" } });
          toast({ title: "Recording uploaded" });
        } catch (e) { toast({ title: "Recording upload failed", description: e?.response?.data?.detail || "" }); }
      };
      mr.start(1000);
      setRecording(true);
      toast({ title: "Recording started" });
    } catch (e) { toast({ title: "Cannot record", description: e.message }); }
  };
  const stopRecording = () => {
    if (recorderRef.current) recorderRef.current.stop();
    setRecording(false);
  };

  const endCall = (navigateToEnd = true) => {
    try { if (recorderRef.current && recorderRef.current.state === "recording") recorderRef.current.stop(); } catch {}
    if (pcRef.current) { try { pcRef.current.close(); } catch {} pcRef.current = null; }
    if (wsRef.current) { try { wsRef.current.close(); } catch {} wsRef.current = null; }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((t) => t.stop());
      localStreamRef.current = null;
    }
    setLocalStream(null);
    if (navigateToEnd) setStage("ended");
  };

  return (
    <div className="min-h-screen bg-[#0e1a14] text-[#f6f1e6] flex flex-col" data-testid="telehealth-page">
      <div className="bg-[#7a2a2a] text-[#f6f1e6] text-[11px] tracking-widest uppercase text-center py-1.5 px-4">
        DEMO ENVIRONMENT · NOT HIPAA COMPLIANT · DO NOT ENTER REAL PHI
      </div>
      <div className="border-b border-[#2f4a3a] px-6 py-4 flex items-center justify-between bg-[#1a2a22]">
        <Link to="/portal" className="flex items-center gap-2 text-sm text-[#c19a4b] hover:text-[#f6f1e6]">
          <ArrowLeft size={16} /> Back to portal
        </Link>
        <div className="text-sm">
          <span className="text-[#8a9a8e]">Telehealth visit</span>
          {appt && <span className="ml-3 text-[#f6f1e6]">{new Date(appt.start).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span>}
        </div>
        <div className="text-xs text-[#8a9a8e]">{user?.email}</div>
      </div>

      <div className="flex-1 p-6 md:p-10 max-w-6xl mx-auto w-full">
        {stage === "loading" && (
          <div className="text-center text-[#8a9a8e] py-16"><Loader2 className="inline animate-spin mr-2" size={18} /> Loading visit…</div>
        )}

        {stage === "error" && (
          <Panel>
            <div className="flex items-center gap-3 text-[#e9b5b5]">
              <AlertCircle size={22} />
              <div className="font-display text-2xl">Something went wrong</div>
            </div>
            <p className="text-[#c8d4cc] mt-3">{errMsg}</p>
            <Button onClick={() => navigate("/portal")} className="mt-5 rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">
              Back to portal
            </Button>
          </Panel>
        )}

        {stage === "consent" && (
          <Panel data-testid="telehealth-consent-panel">
            <div className="flex items-center gap-2 text-[#c19a4b] mb-4">
              <ShieldCheck size={20} /> <span className="eyebrow">Telehealth consent</span>
            </div>
            <h1 className="font-display text-3xl md:text-4xl mb-3">Before we connect</h1>
            <p className="text-[#c8d4cc] mb-6 leading-relaxed">
              Telehealth visits use secure video to connect you with your practitioner. We follow the same
              clinical standards as an in-person visit. For emergencies, call 911 immediately.
            </p>
            <ul className="space-y-2 text-sm text-[#c8d4cc] mb-6">
              <li>• I understand the risks and benefits of telehealth.</li>
              <li>• I am physically located in a state where my provider is licensed.</li>
              <li>• I will be in a private space during the visit.</li>
              <li>• I consent to receive care via video.</li>
            </ul>
            <label className="flex items-center gap-2 mb-4">
              <Checkbox checked={consent.acknowledged} onCheckedChange={(v) => setConsent({ ...consent, acknowledged: !!v })} data-testid="telehealth-consent-cb" />
              <span className="text-sm">I acknowledge and consent to the telehealth visit</span>
            </label>
            <div className="mb-6 max-w-md">
              <Label className="text-[#c8d4cc]">Type your full name as e-signature</Label>
              <Input className="mt-2 bg-[#0e1a14] border-[#2f4a3a] text-[#f6f1e6]" value={consent.signature} onChange={(e) => setConsent({ ...consent, signature: e.target.value })} data-testid="telehealth-consent-sig" />
            </div>
            <Button onClick={submitConsent} disabled={!consent.acknowledged || !consent.signature.trim()}
              className="rounded-full h-11 bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]" data-testid="telehealth-consent-submit">
              <CheckCircle2 size={16} className="mr-2" /> Continue
            </Button>
          </Panel>
        )}

        {stage === "tech" && (
          <Panel data-testid="telehealth-tech-panel">
            <h1 className="font-display text-3xl mb-2">Test your camera & microphone</h1>
            <p className="text-[#c8d4cc] mb-6">Make sure you can be seen and heard before joining.</p>
            <div className="rounded-2xl bg-[#0e1a14] border border-[#2f4a3a] overflow-hidden aspect-video relative max-w-2xl mx-auto mb-6">
              <video ref={localVideoRef} autoPlay muted playsInline className="w-full h-full object-cover" data-testid="techcheck-video" />
              {!localStream && (
                <div className="absolute inset-0 flex items-center justify-center text-[#8a9a8e]">
                  <Loader2 className="animate-spin mr-2" size={18} /> Requesting camera & mic…
                </div>
              )}
              <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-2">
                <button onClick={toggleMic} className={`p-3 rounded-full ${micOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"} text-[#f6f1e6]`} data-testid="techcheck-mic-toggle">
                  {micOn ? <Mic size={16} /> : <MicOff size={16} />}
                </button>
                <button onClick={toggleCam} className={`p-3 rounded-full ${camOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"} text-[#f6f1e6]`} data-testid="techcheck-cam-toggle">
                  {camOn ? <Video size={16} /> : <VideoOff size={16} />}
                </button>
              </div>
            </div>
            <div className="flex justify-end">
              <Button onClick={startCall} disabled={!localStream}
                className="rounded-full h-11 bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]" data-testid="telehealth-join-btn">
                <Video size={16} className="mr-2" /> Join visit
              </Button>
            </div>
          </Panel>
        )}

        {stage === "in-call" && (
          <div className="grid lg:grid-cols-[1fr_320px] gap-4 h-[75vh]" data-testid="telehealth-in-call">
            {/* Video stage */}
            <div className="rounded-2xl border border-[#2f4a3a] bg-black relative overflow-hidden">
              <video ref={remoteVideoRef} autoPlay playsInline className="w-full h-full object-cover" data-testid="remote-video" />
              {!peerOnline && (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-[#8a9a8e] bg-[#0e1a14]/90">
                  <Loader2 className="animate-spin mb-3" size={28} />
                  <p className="text-sm">Waiting for the {isProvider ? "client" : "provider"} to join…</p>
                </div>
              )}
              {/* Local PIP */}
              <div className="absolute bottom-4 right-4 w-40 aspect-video rounded-lg overflow-hidden border-2 border-[#c19a4b] shadow-lg">
                <video ref={localVideoRef} autoPlay muted playsInline className="w-full h-full object-cover" />
              </div>
              {/* Controls */}
              <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-2 bg-[#0e1a14]/80 rounded-full px-3 py-2 backdrop-blur">
                <button onClick={toggleMic} className={`p-3 rounded-full ${micOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"}`} title="Mic" data-testid="call-mic-toggle">
                  {micOn ? <Mic size={16} /> : <MicOff size={16} />}
                </button>
                <button onClick={toggleCam} className={`p-3 rounded-full ${camOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"}`} title="Camera" data-testid="call-cam-toggle">
                  {camOn ? <Video size={16} /> : <VideoOff size={16} />}
                </button>
                <button onClick={toggleScreenShare} className={`p-3 rounded-full ${sharing ? "bg-[#c19a4b] text-[#1f2a22]" : "bg-[#2f4a3a]"}`} title="Share screen" data-testid="call-share-toggle">
                  <MonitorUp size={16} />
                </button>
                <button onClick={() => setChatOpen((v) => !v)} className={`p-3 rounded-full ${chatOpen ? "bg-[#c19a4b] text-[#1f2a22]" : "bg-[#2f4a3a]"}`} title="Chat" data-testid="call-chat-toggle">
                  <MessageSquare size={16} />
                </button>
                {isProvider && (
                  <button onClick={recording ? stopRecording : startRecording} className={`p-3 rounded-full ${recording ? "bg-[#7a2a2a]" : "bg-[#2f4a3a]"}`} title="Record" data-testid="call-record-toggle">
                    {recording ? <Square size={16} fill="currentColor" /> : <Circle size={16} />}
                  </button>
                )}
                <button onClick={() => endCall(true)} className="p-3 rounded-full bg-[#7a2a2a]" title="Leave" data-testid="call-leave">
                  <PhoneOff size={16} />
                </button>
              </div>
              {recording && (
                <div className="absolute top-4 left-4 flex items-center gap-2 bg-[#7a2a2a] px-3 py-1.5 rounded-full text-xs animate-pulse">
                  <Circle size={10} fill="currentColor" /> RECORDING
                </div>
              )}
            </div>

            {/* Chat sidebar */}
            <aside className={`rounded-2xl border border-[#2f4a3a] bg-[#1a2a22] flex flex-col overflow-hidden ${chatOpen ? "" : "hidden lg:flex"}`} data-testid="call-chat-panel">
              <div className="p-3 border-b border-[#2f4a3a] eyebrow text-[#c19a4b]">Visit chat</div>
              <div className="flex-1 overflow-y-auto p-3 space-y-2 text-sm" data-testid="chat-messages">
                {chatMsgs.length === 0 && <div className="text-[#8a9a8e] text-xs">No messages yet.</div>}
                {chatMsgs.map((m, i) => (
                  <div key={i} className={`flex ${m.from === role ? "justify-end" : "justify-start"}`}>
                    <div className={`px-3 py-1.5 rounded-2xl max-w-[80%] ${m.from === role ? "bg-[#2f4a3a] text-[#f6f1e6]" : "bg-[#0e1a14] text-[#c8d4cc] border border-[#2f4a3a]"}`}>
                      <div className="text-[10px] uppercase tracking-wider opacity-70 mb-0.5">{m.from}</div>
                      {m.body}
                    </div>
                  </div>
                ))}
              </div>
              <form onSubmit={(e) => { e.preventDefault(); sendChat(); }} className="p-2 border-t border-[#2f4a3a] flex gap-2">
                <Input className="bg-[#0e1a14] border-[#2f4a3a] text-[#f6f1e6]" value={chatDraft}
                  onChange={(e) => setChatDraft(e.target.value)} placeholder="Type a message…" data-testid="chat-input" />
                <Button type="submit" className="bg-[#c19a4b] text-[#1f2a22] hover:bg-[#a8853f]" data-testid="chat-send">
                  <Send size={14} />
                </Button>
              </form>
            </aside>
          </div>
        )}

        {stage === "ended" && (
          <Panel>
            <div className="text-center py-8">
              <CheckCircle2 size={40} className="text-[#c19a4b] mx-auto mb-3" />
              <h1 className="font-display text-3xl mb-2">Visit ended</h1>
              <p className="text-[#c8d4cc] mb-6">Thank you. A visit summary will be available in your chart.</p>
              <Button onClick={() => navigate("/portal")} className="rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">
                Back to portal
              </Button>
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

function Panel({ children, ...rest }) {
  return <div className="rounded-2xl border border-[#2f4a3a] bg-[#1a2a22] p-6 md:p-10" {...rest}>{children}</div>;
}
