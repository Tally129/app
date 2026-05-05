import React from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import Logo from "../components/Logo";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { useToast } from "../hooks/use-toast";
import { Loader2, CheckCircle2, ShieldCheck, FileText } from "lucide-react";
import { FieldRenderer, SignaturePad } from "./admin/AdminFormsConsents";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Public, no-auth-required form responder.
 * Patient opens /forms/respond/:token, fills in the form, and signs.
 */
export default function FormResponder() {
  const { token } = useParams();
  const { toast } = useToast();
  const [tpl, setTpl] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [answers, setAnswers] = React.useState({});
  const [signature, setSignature] = React.useState(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [done, setDone] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    axios.get(`${API}/public/forms/${token}`)
      .then((r) => { if (active) setTpl(r.data); })
      .catch((e) => { if (active) setError(e?.response?.data?.detail || "This link is invalid or expired."); })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [token]);

  const setAnswer = (id, v) => setAnswers((prev) => ({ ...prev, [id]: v }));

  const submit = async () => {
    if (!tpl) return;
    // Validate required
    for (const f of tpl.fields || []) {
      if (f.required) {
        if (f.type === "signature") {
          if (!signature) { toast({ title: "Signature required" }); return; }
        } else {
          const v = answers[f.id];
          if (v === undefined || v === null || v === "" || v === false) {
            toast({ title: "Missing answer", description: f.label });
            return;
          }
        }
      }
    }
    setSubmitting(true);
    try {
      await axios.post(`${API}/public/forms/${token}/submit`, {
        answers,
        signature_data: signature,
      });
      setDone(true);
    } catch (e) {
      toast({ title: "Submit failed", description: e?.response?.data?.detail || "Try again." });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <div className="text-center py-20 text-[#6a6a6a]">
          <Loader2 size={28} className="inline animate-spin mr-2" /> Loading form…
        </div>
      </Shell>
    );
  }
  if (error) {
    return (
      <Shell>
        <div className="rounded-2xl border border-[#d4a8a8] bg-[#f5e3e3] p-10 text-center">
          <h1 className="font-display text-3xl text-[#7a2a2a]">Link unavailable</h1>
          <p className="text-[#5a5a5a] mt-3">{error}</p>
          <p className="text-xs text-[#6a6a6a] mt-4">Please contact Natural Medical Solutions for a new link.</p>
        </div>
      </Shell>
    );
  }
  if (done || tpl?.already_submitted) {
    return (
      <Shell>
        <div className="rounded-2xl border border-[#a8bfa8] bg-[#dde9dd] p-10 text-center">
          <CheckCircle2 size={42} className="text-[#2f4a3a] mx-auto mb-3" />
          <h1 className="font-display text-3xl text-[#1f2a22]">Thank you</h1>
          <p className="text-[#3a3a3a] mt-3">Your form has been submitted to Natural Medical Solutions.</p>
          <p className="text-xs text-[#6a6a6a] mt-2">A confirmation will appear in your patient portal at your next visit.</p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-7 md:p-10" data-testid="form-responder-page">
        <div className="flex items-start gap-3 mb-4">
          <FileText size={22} className="text-[#8a6a3c] mt-1" />
          <div>
            <h1 className="font-display text-3xl text-[#1f2a22]">{tpl.title}</h1>
            {tpl.client_name && <p className="text-xs uppercase tracking-widest text-[#8a6a3c] mt-1">For {tpl.client_name}</p>}
          </div>
        </div>
        {tpl.description && <p className="text-[#5a5a5a] mb-7 max-w-2xl">{tpl.description}</p>}

        <div className="space-y-6">
          {(tpl.fields || []).map((f) => (
            <div key={f.id} className="space-y-2">
              <Label className="text-[#1f2a22]">
                {f.label}{f.required && <span className="text-[#7a2a2a]"> *</span>}
              </Label>
              {f.type === "signature" ? (
                <SignaturePad value={signature} onChange={setSignature} />
              ) : (
                <FieldRenderer field={f} value={answers[f.id]} onChange={(v) => setAnswer(f.id, v)} />
              )}
              {f.help_text && <p className="text-xs text-[#6a6a6a]">{f.help_text}</p>}
            </div>
          ))}
        </div>

        <div className="mt-8 pt-6 border-t border-[#e7dfc9] flex flex-col md:flex-row md:items-center justify-between gap-3">
          <p className="text-xs text-[#6a6a6a] inline-flex items-center gap-1.5"><ShieldCheck size={12} /> Submitted securely to Natural Medical Solutions.</p>
          <Button
            onClick={submit}
            disabled={submitting}
            className="rounded-full h-11 px-7 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
            data-testid="form-responder-submit"
          >
            {submitting ? <Loader2 size={14} className="animate-spin mr-2" /> : null}
            {submitting ? "Submitting…" : "Submit form"}
          </Button>
        </div>
      </div>
    </Shell>
  );
}

function Shell({ children }) {
  return (
    <div className="min-h-screen bg-parchment font-body text-[#2a2a2a]">
      <div className="top-ribbon" />
      <header className="border-b border-[#e7dfc9] bg-[#fbf7ee]">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3">
            <Logo size={42} withText={false} />
            <span className="font-display text-lg text-[#1f2a22] hidden sm:inline">Natural Medical Solutions</span>
          </Link>
          <span className="text-xs uppercase tracking-widest text-[#8a6a3c]">Patient form</span>
        </div>
      </header>
      <main className="max-w-3xl mx-auto px-4 py-10">{children}</main>
    </div>
  );
}
