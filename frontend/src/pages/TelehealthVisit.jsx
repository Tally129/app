import React from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import DailyIframe from "@daily-co/daily-js";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Checkbox } from "../components/ui/checkbox";
import { useToast } from "../hooks/use-toast";
import {
  Video, Mic, MicOff, VideoOff, PhoneOff, ArrowLeft,
  ShieldCheck, AlertCircle, Loader2, CheckCircle2, Wifi, Settings2,
} from "lucide-react";

/**
 * Telehealth visit — SimplePractice/Tebra-style flow:
 *   1. Pre-visit: appointment summary + tech check (camera/mic preview)
 *   2. Consent (clients only): typed e-signature
 *   3. Waiting room: provider hasn't joined yet, polling
 *   4. In-call: Daily Prebuilt iframe with NMS theme + leave button
 *   5. Post-call: redirect to chart/visit summary
 */
export default function TelehealthVisit() {
  const { id } = useParams();
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [loading, setLoading] = React.useState(true);
  const [appt, setAppt] = React.useState(null);
  const [stage, setStage] = React.useState("loading"); // loading | consent | tech | join | in-call | ended | error
  const [consent, setConsent] = React.useState({ acknowledged: false, signature: "" });
  const [techStream, setTechStream] = React.useState(null);
  const [micOn, setMicOn] = React.useState(true);
  const [camOn, setCamOn] = React.useState(true);
  const [errMsg, setErrMsg] = React.useState("");

  const techVideoRef = React.useRef(null);
  const callContainerRef = React.useRef(null);
  const dailyFrameRef = React.useRef(null);

  const isProvider = user?.role !== "client";

  // Load appointment
  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/appointments");
      const mine = (r.data || []).find((a) => a.id === id);
      if (!mine) {
        setErrMsg("Appointment not found.");
        setStage("error");
        return;
      }
      setAppt(mine);
      // Decide first stage
      if (user?.role === "client" && !mine.consent_telehealth) {
        setStage("consent");
      } else {
        setStage("tech");
      }
    } catch (e) {
      setErrMsg(e?.response?.data?.detail || "Could not load visit.");
      setStage("error");
    } finally {
      setLoading(false);
    }
  }, [id, user?.role]);

  React.useEffect(() => { load(); }, [load]);

  // Tech check media
  const startTechCheck = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      setTechStream(s);
      if (techVideoRef.current) techVideoRef.current.srcObject = s;
    } catch (e) {
      toast({ title: "Camera/mic blocked", description: "Please allow camera and microphone access in your browser." });
    }
  };

  React.useEffect(() => {
    if (stage === "tech" && !techStream) startTechCheck();
    return () => {
      if (techStream) techStream.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line
  }, [stage]);

  const toggleMic = () => {
    if (!techStream) return;
    techStream.getAudioTracks().forEach((t) => (t.enabled = !micOn));
    setMicOn((v) => !v);
  };
  const toggleCam = () => {
    if (!techStream) return;
    techStream.getVideoTracks().forEach((t) => (t.enabled = !camOn));
    setCamOn((v) => !v);
  };

  const submitConsent = async () => {
    if (!consent.acknowledged || !consent.signature.trim()) {
      toast({ title: "Please acknowledge and type your name to consent." });
      return;
    }
    try {
      await api.post(`/appointments/${id}/telehealth/consent`, { signature: consent.signature.trim() });
      toast({ title: "Consent recorded" });
      // Reload appt + advance
      await load();
      setStage("tech");
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    }
  };

  // Get token + start Daily call
  const joinCall = async () => {
    setStage("join");
    try {
      // Make sure room exists (idempotent for providers)
      if (isProvider) {
        try { await api.post(`/appointments/${id}/telehealth/room`); } catch {}
      }
      const r = await api.get(`/appointments/${id}/telehealth/token`);
      const { room_url, token, _stubbed } = r.data;

      // Stop tech-check stream so it doesn't compete
      if (techStream) techStream.getTracks().forEach((t) => t.stop());
      setTechStream(null);

      setStage("in-call");

      if (_stubbed || !room_url) {
        // STUBBED demo: show a placeholder pane
        return;
      }

      // Mount Daily Prebuilt iframe
      // small delay to ensure container is mounted
      setTimeout(() => {
        if (!callContainerRef.current) return;
        const frame = DailyIframe.createFrame(callContainerRef.current, {
          showLeaveButton: true,
          iframeStyle: {
            width: "100%",
            height: "100%",
            border: "0",
            borderRadius: "16px",
          },
          theme: {
            colors: {
              accent: "#2f4a3a",
              accentText: "#f6f1e6",
              background: "#0e1a14",
              backgroundAccent: "#1a2a22",
              baseText: "#f6f1e6",
              border: "#2f4a3a",
              mainAreaBg: "#0e1a14",
              mainAreaBgAccent: "#1a2a22",
              mainAreaText: "#f6f1e6",
              supportiveText: "#c19a4b",
            },
          },
        });
        dailyFrameRef.current = frame;
        frame.on("left-meeting", () => {
          frame.destroy();
          dailyFrameRef.current = null;
          setStage("ended");
        });
        frame.on("error", (err) => {
          console.error("Daily error", err);
          setErrMsg(err?.errorMsg || "Video call error");
        });
        frame.join({ url: room_url, token: token || undefined });
      }, 100);
    } catch (e) {
      setErrMsg(e?.response?.data?.detail || "Could not start the call.");
      setStage("error");
    }
  };

  // Cleanup Daily on unmount
  React.useEffect(() => {
    return () => {
      if (dailyFrameRef.current) {
        try { dailyFrameRef.current.destroy(); } catch {}
        dailyFrameRef.current = null;
      }
    };
  }, []);

  return (
    <div className="min-h-screen bg-[#0e1a14] text-[#f6f1e6] flex flex-col" data-testid="telehealth-page">
      {/* Header */}
      <div className="bg-[#7a2a2a] text-[#f6f1e6] text-[11px] tracking-widest uppercase text-center py-1.5 px-4">
        DEMO ENVIRONMENT · NOT HIPAA COMPLIANT · DO NOT ENTER REAL PHI
      </div>
      <div className="border-b border-[#2f4a3a] px-6 py-4 flex items-center justify-between bg-[#1a2a22]">
        <Link to="/portal" className="flex items-center gap-2 text-sm text-[#c19a4b] hover:text-[#f6f1e6]">
          <ArrowLeft size={16} /> Back to portal
        </Link>
        <div className="text-sm">
          <span className="text-[#8a9a8e]">Telehealth visit</span>
          {appt && <span className="ml-3 text-[#f6f1e6]">{new Date(appt.start_time).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span>}
        </div>
        <div className="text-xs text-[#8a9a8e]">{user?.email}</div>
      </div>

      <div className="flex-1 p-6 md:p-10 max-w-5xl mx-auto w-full">
        {loading && (
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

        {/* CONSENT */}
        {stage === "consent" && (
          <Panel data-testid="telehealth-consent-panel">
            <div className="flex items-center gap-2 text-[#c19a4b] mb-4">
              <ShieldCheck size={20} /> <span className="eyebrow">Telehealth consent</span>
            </div>
            <h1 className="font-display text-3xl md:text-4xl mb-3">Before we connect</h1>
            <p className="text-[#c8d4cc] mb-6 leading-relaxed">
              Telehealth visits use secure video to connect you with your practitioner. We follow the same
              clinical standards as an in-person visit. Recording and screenshots are not permitted by either party.
              For emergencies, call 911 immediately.
            </p>
            <ul className="space-y-2 text-sm text-[#c8d4cc] mb-6">
              <li>• I understand the risks and benefits of telehealth.</li>
              <li>• I am physically located in a state where my provider is licensed.</li>
              <li>• I will be in a private space during the visit.</li>
              <li>• I consent to receive care via video.</li>
            </ul>
            <label className="flex items-center gap-2 mb-4">
              <Checkbox
                checked={consent.acknowledged}
                onCheckedChange={(v) => setConsent({ ...consent, acknowledged: !!v })}
                data-testid="telehealth-consent-cb"
              />
              <span className="text-sm">I acknowledge and consent to the telehealth visit</span>
            </label>
            <div className="mb-6 max-w-md">
              <Label className="text-[#c8d4cc]">Type your full name as e-signature</Label>
              <Input
                className="mt-2 bg-[#0e1a14] border-[#2f4a3a] text-[#f6f1e6]"
                value={consent.signature}
                onChange={(e) => setConsent({ ...consent, signature: e.target.value })}
                data-testid="telehealth-consent-sig"
              />
            </div>
            <Button
              onClick={submitConsent}
              disabled={!consent.acknowledged || !consent.signature.trim()}
              className="rounded-full h-11 bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"
              data-testid="telehealth-consent-submit"
            >
              <CheckCircle2 size={16} className="mr-2" /> Continue
            </Button>
          </Panel>
        )}

        {/* TECH CHECK */}
        {stage === "tech" && (
          <Panel data-testid="telehealth-tech-panel">
            <div className="flex items-center gap-2 text-[#c19a4b] mb-2">
              <Settings2 size={18} /> <span className="eyebrow">Tech check</span>
            </div>
            <h1 className="font-display text-3xl mb-2">Test your camera & microphone</h1>
            <p className="text-[#c8d4cc] mb-6">Make sure you can be seen and heard before joining.</p>

            <div className="rounded-2xl bg-[#0e1a14] border border-[#2f4a3a] overflow-hidden aspect-video relative max-w-2xl mx-auto mb-6">
              <video ref={techVideoRef} autoPlay muted playsInline className="w-full h-full object-cover" data-testid="techcheck-video" />
              {!techStream && (
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

            <div className="flex flex-wrap gap-3 items-center justify-between">
              <div className="text-xs text-[#8a9a8e] flex items-center gap-2">
                <Wifi size={12} /> Strong network recommended
              </div>
              <Button
                onClick={joinCall}
                disabled={!techStream}
                className="rounded-full h-11 bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"
                data-testid="telehealth-join-btn"
              >
                <Video size={16} className="mr-2" /> Join visit
              </Button>
            </div>
          </Panel>
        )}

        {stage === "join" && (
          <Panel>
            <div className="text-center py-12">
              <Loader2 className="inline animate-spin mr-2" size={20} /> Connecting to room…
            </div>
          </Panel>
        )}

        {/* IN CALL */}
        {stage === "in-call" && (
          <div className="rounded-2xl border border-[#2f4a3a] bg-[#0e1a14] h-[70vh]" data-testid="telehealth-in-call">
            <div ref={callContainerRef} className="w-full h-full" />
            {/* Stub fallback */}
            <div className="text-center text-[#8a9a8e] -mt-[60vh] pointer-events-none flex flex-col items-center justify-center h-[60vh] daily-stub-fallback opacity-0">
              <Video size={36} className="text-[#c19a4b] mb-3" />
              <p>Daily.co room (stub mode)</p>
              <p className="text-xs mt-2">Add DAILY_API_KEY env var to enable live video.</p>
            </div>
            <div className="flex justify-end px-3 pb-3 gap-2 -mt-12 relative z-10">
              <Button
                variant="outline"
                onClick={() => { if (dailyFrameRef.current) dailyFrameRef.current.leave(); else setStage("ended"); }}
                className="rounded-full bg-[#7a2a2a] border-[#7a2a2a] text-[#f6f1e6] hover:bg-[#5e1f1f]"
                data-testid="telehealth-leave-btn"
              >
                <PhoneOff size={14} className="mr-2" /> Leave visit
              </Button>
            </div>
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
  return (
    <div className="rounded-2xl border border-[#2f4a3a] bg-[#1a2a22] p-6 md:p-10" {...rest}>
      {children}
    </div>
  );
}
