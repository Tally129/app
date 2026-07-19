import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Checkbox } from "../../components/ui/checkbox";
import { useToast } from "../../hooks/use-toast";
import { Check, ChevronLeft, ChevronRight, Save } from "lucide-react";
import { getErrorMessage } from "../../lib/errors";

const STEPS = ["Demographics", "Health history", "Symptoms", "Lifestyle", "Consent"];

export default function PatientIntake() {
  const { toast } = useToast();
  const [step, setStep] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [clientId, setClientId] = React.useState(null);
  const [form, setForm] = React.useState({
    demographics: { dob: "", sex: "", address: "", emergency_contact: "" },
    health_history: { conditions: "", medications: "", allergies: "", surgeries: "", family_history: "" },
    symptoms: { primary: "", duration: "", severity: "5", other: "" },
    lifestyle: { diet: "", exercise: "", sleep_hours: "", stress: "", alcohol: "", smoking: "" },
    consent: { signed: false, signature: "", acknowledgement: false },
  });

  React.useEffect(() => {
    (async () => {
      try {
        const me = await api.get("/clients/me");
        setClientId(me.data.id);
        const existing = await api.get(`/intake/${me.data.id}`);
        if (existing.data) {
          setForm({
            demographics: existing.data.demographics || form.demographics,
            health_history: existing.data.health_history || form.health_history,
            symptoms: existing.data.symptoms || form.symptoms,
            lifestyle: existing.data.lifestyle || form.lifestyle,
            consent: existing.data.consent || form.consent,
          });
        }
      } catch (e) {
        // ignore
      } finally {
        setLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  const update = (section, field, value) =>
    setForm((p) => ({ ...p, [section]: { ...p[section], [field]: value } }));

  const saveDraft = async (completed = false) => {
    setSaving(true);
    try {
      await api.post("/intake", {
        client_id: clientId,
        demographics: form.demographics,
        health_history: form.health_history,
        symptoms: form.symptoms,
        lifestyle: form.lifestyle,
        consent: form.consent,
        completed,
      });
      toast({
        title: completed ? "Intake submitted" : "Progress saved",
        description: completed
          ? "Dr. Ravello\u2019s team will review before your visit."
          : "You can continue any time.",
      });
    } catch (e) {
      toast({ title: "Save failed", description: getErrorMessage(e) || "Please try again." });
    } finally {
      setSaving(false);
    }
  };

  if (loading)
    return (
      <PortalLayout>
        <div className="text-[#6a6a6a]">Loading intake…</div>
      </PortalLayout>
    );

  return (
    <PortalLayout>
      <PortalHeader
        title="Health Intake"
        subtitle="All answers are private and used only to tailor your care."
      />

      {/* Stepper */}
      <div className="mb-8 flex items-center gap-2 overflow-x-auto">
        {STEPS.map((s, i) => (
          <React.Fragment key={s}>
            <button
              onClick={() => setStep(i)}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs whitespace-nowrap transition ${
                i === step
                  ? "bg-[#2f4a3a] text-[#f6f1e6]"
                  : i < step
                  ? "bg-[#e7dfc9] text-[#2f4a3a]"
                  : "bg-[#fbf7ee] border border-[#e7dfc9] text-[#8a8a8a]"
              }`}
            >
              {i < step ? <Check size={12} /> : <span className="w-4 text-center">{i + 1}</span>}
              {s}
            </button>
            {i < STEPS.length - 1 && <span className="h-px w-4 bg-[#e7dfc9]" />}
          </React.Fragment>
        ))}
      </div>

      <div className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 md:p-8 space-y-5">
        {step === 0 && (
          <div className="grid md:grid-cols-2 gap-5">
            <div><Label>Date of birth</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="date" value={form.demographics.dob} onChange={(e) => update("demographics", "dob", e.target.value)} /></div>
            <div><Label>Sex assigned at birth</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.demographics.sex} onChange={(e) => update("demographics", "sex", e.target.value)} /></div>
            <div className="md:col-span-2"><Label>Address</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.demographics.address} onChange={(e) => update("demographics", "address", e.target.value)} /></div>
            <div className="md:col-span-2"><Label>Emergency contact</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" placeholder="Name & phone" value={form.demographics.emergency_contact} onChange={(e) => update("demographics", "emergency_contact", e.target.value)} /></div>
          </div>
        )}

        {step === 1 && (
          <div className="grid gap-5">
            <div><Label>Current conditions / diagnoses</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] min-h-[80px]" value={form.health_history.conditions} onChange={(e) => update("health_history", "conditions", e.target.value)} /></div>
            <div><Label>Current medications & supplements</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] min-h-[80px]" value={form.health_history.medications} onChange={(e) => update("health_history", "medications", e.target.value)} /></div>
            <div className="grid md:grid-cols-2 gap-5">
              <div><Label>Allergies</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.health_history.allergies} onChange={(e) => update("health_history", "allergies", e.target.value)} /></div>
              <div><Label>Past surgeries</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.health_history.surgeries} onChange={(e) => update("health_history", "surgeries", e.target.value)} /></div>
            </div>
            <div><Label>Family history</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] min-h-[80px]" value={form.health_history.family_history} onChange={(e) => update("health_history", "family_history", e.target.value)} /></div>
          </div>
        )}

        {step === 2 && (
          <div className="grid gap-5">
            <div><Label>Primary concern</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.symptoms.primary} onChange={(e) => update("symptoms", "primary", e.target.value)} /></div>
            <div className="grid md:grid-cols-2 gap-5">
              <div><Label>Duration</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" placeholder="e.g. 6 months" value={form.symptoms.duration} onChange={(e) => update("symptoms", "duration", e.target.value)} /></div>
              <div><Label>Severity (1–10)</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="number" min="1" max="10" value={form.symptoms.severity} onChange={(e) => update("symptoms", "severity", e.target.value)} /></div>
            </div>
            <div><Label>Other symptoms</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] min-h-[80px]" value={form.symptoms.other} onChange={(e) => update("symptoms", "other", e.target.value)} /></div>
          </div>
        )}

        {step === 3 && (
          <div className="grid md:grid-cols-2 gap-5">
            <div><Label>Typical diet</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.lifestyle.diet} onChange={(e) => update("lifestyle", "diet", e.target.value)} /></div>
            <div><Label>Exercise</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.lifestyle.exercise} onChange={(e) => update("lifestyle", "exercise", e.target.value)} /></div>
            <div><Label>Sleep (hrs / night)</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.lifestyle.sleep_hours} onChange={(e) => update("lifestyle", "sleep_hours", e.target.value)} /></div>
            <div><Label>Stress level</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.lifestyle.stress} onChange={(e) => update("lifestyle", "stress", e.target.value)} /></div>
            <div><Label>Alcohol</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.lifestyle.alcohol} onChange={(e) => update("lifestyle", "alcohol", e.target.value)} /></div>
            <div><Label>Smoking</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.lifestyle.smoking} onChange={(e) => update("lifestyle", "smoking", e.target.value)} /></div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-5">
            <div className="text-sm text-[#5a5a5a] leading-relaxed bg-[#f6f1e6] border border-[#e0d6bc] rounded-xl p-4">
              I understand that naturopathic care is complementary and does not replace emergency or diagnostic medical services. I consent to the collection of my health information for the purpose of personalized care at Natural Medical Solutions. I acknowledge this is a demo environment and will not enter real protected health information.
            </div>
            <label className="flex items-start gap-3 cursor-pointer">
              <Checkbox
                checked={form.consent.acknowledgement}
                onCheckedChange={(c) => update("consent", "acknowledgement", !!c)}
                className="mt-0.5"
              />
              <span className="text-sm">I acknowledge and agree to the terms above.</span>
            </label>
            <div>
              <Label>Electronic signature (type full name)</Label>
              <Input
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                value={form.consent.signature}
                onChange={(e) => {
                  const v = e.target.value;
                  setForm((p) => ({
                    ...p,
                    consent: { ...p.consent, signature: v, signed: !!v && p.consent.acknowledgement },
                  }));
                }}
              />
            </div>
          </div>
        )}

        <div className="flex flex-col sm:flex-row justify-between gap-3 pt-4 border-t border-[#e7dfc9]">
          <Button
            type="button"
            variant="outline"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            className="btn-lift rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6] disabled:opacity-40"
          >
            <ChevronLeft size={16} className="mr-1" /> Back
          </Button>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => saveDraft(false)}
              disabled={saving}
              className="btn-lift rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6]"
            >
              <Save size={16} className="mr-1" /> Save draft
            </Button>
            {step < STEPS.length - 1 ? (
              <Button
                type="button"
                onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
                className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
              >
                Next <ChevronRight size={16} className="ml-1" />
              </Button>
            ) : (
              <Button
                type="button"
                disabled={!form.consent.acknowledgement || !form.consent.signature || saving}
                onClick={() => saveDraft(true)}
                className="btn-lift rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"
              >
                Submit intake
              </Button>
            )}
          </div>
        </div>
      </div>
    </PortalLayout>
  );
}