import React from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Checkbox } from "../components/ui/checkbox";
import { useToast } from "../hooks/use-toast";
import { Video, Mic, MicOff, VideoOff, PhoneOff, Circle, ArrowLeft, ShieldCheck, AlertCircle } from "lucide-react";

export default function TelehealthVisit() {
  const { id } = useParams();
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [loading, setLoading] = React.useState(true);
  const [appt, setAppt] = React.useState(null);
  const [session, setSession] = React.useState(null);
  const [needConsent, setNeedConsent] = React.useState(false);
  const [consent, setConsent] = React.useState({ acknowledged: false, signature: "" });
  const [inCall, setInCall] = React.useState(false);
  const [techOk, setTechOk] = React.useState(false);
  const [mediaStream, setMediaStream] = React.useState(null);
  const [micOn, setMicOn] = React.useState(true);
  const [camOn, setCamOn] = React.useState(true);
  const [recording, setRecording] = React.useState(false);
  const videoRef = React.useRef(null);
  const iframeRef = React.useRef(null);

  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/appointments", { params: { client_id: undefined } });
      const mine = (r.data || []).find((a) => a.id === id);
      setAppt(mine);
      if (user?.role === "client" && !mine?.consent_telehealth) {
        setNeedConsent(true);
      }
    } finally { setLoading(false); }
  }, [id, user?.role]);

  React.useEffect(() => { load(); }, [load]);

  const requestCamera = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      setMediaStream(s);
      if (videoRef.current) videoRef.current.srcObject = s;
      setTechOk(true);
    } catch (e) {
      toast({ title: "Camera/mic access needed", description: "Please allow access to continue your visit." });
    }
  };

  const giveConsent = async () => {
    if (!consent.acknowledged || !consent.signature) return toast({ title: "Acknowledge and sign to continue" });
    try {
      await api.post(`/appointments/${id}/telehealth/consent`, { signature: consent.signature });
      setNeedConsent(false);
      load();
    } catch (e) { toast({ title: "Failed" }); }
  };

  const joinVisit = async () => {
    try {
      const { data } = await api.get(`/appointments/${id}/telehealth/token`);
      setSession(data);
      setInCall(true);
      // Stop local preview stream (Daily iframe manages its own)
      if (mediaStream) mediaStream.getTracks().forEach((t) => t.stop());
      setMediaStream(null);
    } catch (e) {
      toast({ title: "Couldn’t start visit", description: e?.response?.data?.detail || "Try again." });
    }
  };

  const endCall = () => {
    setInCall(false);
    setSession(null);
    navigate(-1);
  };

  const toggleMic = () => {
    if (!mediaStream) return;
    mediaStream.getAudioTracks().forEach((t) => (t.enabled = !t.enabled));
    setMicOn((v) => !v);
  };
  const toggleCam = () => {
    if (!mediaStream) return;
    mediaStream.getVideoTracks().forEach((t) => (t.enabled = !t.enabled));
    setCamOn((v) => !v);
  };

  const toggleRecording = async () => {
    try {
      await api.post(`/appointments/${id}/telehealth/recording`, { action: recording ? "stop" : "start" });
      setRecording((v) => !v);
      toast({ title: recording ? "Recording stopped" : "Recording started", description: "Patient notified." });
    } catch { toast({ title: "Failed" }); }
  };

  if (loading) return <div className="min-h-screen bg-[#1a1a1a] text-[#f6f1e6] flex items-center justify-center">Loading…</div>;
  if (!appt) return <div className="min-h-screen bg-[#1a1a1a] text-[#f6f1e6] flex items-center justify-center">Appointment not found.</div>;

  const roomUrl = session?.room_url;
  const stubbed = session?._stubbed;

  return (
    <div className="min-h-screen bg-[#101612] text-[#f6f1e6] flex flex-col">
      <div className="bg-[#7a2a2a] text-[#f6f1e6] text-[11px] tracking-widest uppercase text-center py-1.5 px-4">
        DEMO ENVIRONMENT · NOT HIPAA COMPLIANT · DO NOT CONDUCT REAL VISITS
      </div>
      <header className="flex items-center justify-between p-4 border-b border-[#24342a]">
        <Link to={user?.role === "client" ? "/portal/patient/appointments" : "/portal/provider/schedule"} className="text-sm text-[#d7b878] hover:text-[#f6f1e6] inline-flex items-center gap-2">
          <ArrowLeft size={16} /> Exit
        </Link>
        <div className="text-center">
          <div className="text-sm font-display">Telehealth visit</div>
          <div className="text-xs text-[#a8a8a8]">{new Date(appt.start).toLocaleString()}</div>
        </div>
        <div className="text-xs text-[#a8a8a8]">{appt.service || "Consultation"}</div>
      </header>

      {/* Consent gate (patient only) */}
      {needConsent && (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-lg bg-[#1a2420] border border-[#24342a] rounded-3xl p-8">
            <ShieldCheck className="text-[#c19a4b] mb-3" size={28} />
            <h2 className="font-display text-2xl">Telehealth Informed Consent</h2>
            <p className="text-sm text-[#d7d3c4] mt-3 leading-relaxed">
              I understand that a telehealth visit uses video technology to connect me with my provider. I understand the limits and alternatives of telehealth, that I may stop at any time, and that I should dial 911 for emergencies. I consent to this visit being conducted via video.
            </p>
            <label className="mt-5 flex items-start gap-2 cursor-pointer text-sm">
              <Checkbox checked={consent.acknowledged} onCheckedChange={(c) => setConsent({ ...consent, acknowledged: !!c })} className="mt-0.5" />
              I have read and understand the telehealth informed consent.
            </label>
            <div className="mt-4">
              <Label className="text-[#d7d3c4]">Signature (type full name)</Label>
              <Input value={consent.signature} onChange={(e) => setConsent({ ...consent, signature: e.target.value })} className="mt-2 bg-[#101612] border-[#24342a] text-[#f6f1e6]" />
            </div>
            <Button onClick={giveConsent} className="mt-5 w-full h-11 rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">I consent & continue</Button>
          </div>
        </div>
      )}

      {/* Tech check (pre-join) */}
      {!needConsent && !inCall && (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-2xl w-full bg-[#1a2420] border border-[#24342a] rounded-3xl p-8">
            <h2 className="font-display text-2xl">Pre-visit check</h2>
            <p className="text-sm text-[#d7d3c4] mt-2">Test your camera and microphone before joining. You can toggle them off once inside.</p>

            <div className="mt-5 aspect-video bg-black rounded-2xl overflow-hidden relative">
              {mediaStream ? (
                <video ref={videoRef} autoPlay muted playsInline className="w-full h-full object-cover" />
              ) : (
                <div className="absolute inset-0 flex items-center justify-center text-[#d7d3c4] text-sm">
                  Camera off — click “Test camera & mic”
                </div>
              )}
              {mediaStream && (
                <div className="absolute bottom-3 left-3 right-3 flex items-center justify-center gap-3">
                  <Button onClick={toggleMic} size="sm" className={`rounded-full ${micOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"} text-[#f6f1e6]`}>{micOn ? <Mic size={14} /> : <MicOff size={14} />}</Button>
                  <Button onClick={toggleCam} size="sm" className={`rounded-full ${camOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"} text-[#f6f1e6]`}>{camOn ? <Video size={14} /> : <VideoOff size={14} />}</Button>
                </div>
              )}
            </div>

            <div className="mt-5 flex flex-col sm:flex-row gap-3">
              <Button onClick={requestCamera} variant="outline" className="flex-1 rounded-full border-[#c19a4b] text-[#c19a4b] bg-transparent hover:bg-[#c19a4b] hover:text-[#1f2a22]">
                <Video size={16} className="mr-2" /> Test camera & mic
              </Button>
              <Button onClick={joinVisit} disabled={!techOk} className="flex-1 rounded-full bg-[#2f4a3a] hover:bg-[#3a5a48] text-[#f6f1e6] disabled:opacity-40">
                Join visit
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* In-call (Daily.co iframe) */}
      {inCall && (
        <div className="flex-1 flex flex-col">
          {stubbed && (
            <div className="bg-[#3a2a0a] text-[#d7b878] text-xs text-center py-2 flex items-center justify-center gap-2">
              <AlertCircle size={14} /> Daily.co API key not set — this is a placeholder room. Add DAILY_API_KEY to activate real video.
            </div>
          )}
          <div className="flex-1 bg-black relative">
            {stubbed ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center">
                  <div className="w-24 h-24 rounded-full bg-[#c19a4b]/30 border border-[#c19a4b]/60 mx-auto flex items-center justify-center">
                    <Video size={40} className="text-[#c19a4b]" />
                  </div>
                  <div className="mt-6 font-display text-2xl">Stub video room</div>
                  <div className="mt-2 text-sm text-[#d7d3c4]">Room URL: {roomUrl}</div>
                  <div className="mt-1 text-xs text-[#8a8a8a]">When DAILY_API_KEY is configured, this will be replaced with the live call.</div>
                </div>
              </div>
            ) : (
              <iframe
                ref={iframeRef}
                title="telehealth"
                allow="camera; microphone; fullscreen; speaker; display-capture; autoplay"
                src={`${roomUrl}${session?.token ? `?t=${session.token}` : ""}`}
                className="w-full h-full"
              />
            )}
          </div>
          <div className="p-4 border-t border-[#24342a] flex items-center justify-center gap-3">
            {user?.role !== "client" && (
              <Button onClick={toggleRecording} variant="outline" className={`rounded-full ${recording ? "border-[#7a2a2a] text-[#ff7070]" : "border-[#c19a4b] text-[#c19a4b]"} bg-transparent`}>
                <Circle size={12} className={`mr-2 ${recording ? "fill-[#ff7070]" : ""}`} />
                {recording ? "Stop recording" : "Start recording"}
              </Button>
            )}
            <Button onClick={endCall} className="rounded-full bg-[#7a2a2a] hover:bg-[#9a3535] text-[#f6f1e6]">
              <PhoneOff size={14} className="mr-2" /> End visit
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
