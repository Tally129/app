import React from "react";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../components/ui/dialog";
import { useToast } from "../hooks/use-toast";
import { ChevronLeft, ChevronRight, CheckCircle2, User, Phone, Heart, Shield } from "lucide-react";

const STEPS = [
  { key: "demo", label: "Demographics", icon: User },
  { key: "contact", label: "Contact", icon: Phone },
  { key: "wellness", label: "Wellness profile", icon: Heart },
  { key: "consent", label: "Preferences & consent", icon: Shield },
];

const empty = {
  full_name: "", dob: "", sex: "", gender_identity: "", pronouns: "", language: "English", marital_status: "",
  email: "", phone: "", alt_phone: "", address: "", emergency_contact: "",
  primary_concern: "", wellness_goals: "", current_supplements: "", dietary_restrictions: "", allergies: "", referral_source: "",
  comms_pref: "email", consent_telehealth: false, consent_photo: false, consent_marketing: false,
  notes: "",
};

export default function AddPatientWizard({ open, onOpenChange, onCreated }) {
  const { toast } = useToast();
  const [step, setStep] = React.useState(0);
  const [form, setForm] = React.useState(empty);
  const [submitting, setSubmitting] = React.useState(false);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const reset = () => { setForm(empty); setStep(0); };

  const next = () => {
    if (step === 0 && !form.full_name.trim()) {
      toast({ title: "Name is required" });
      return;
    }
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  };
  const back = () => setStep((s) => Math.max(0, s - 1));

  const submit = async () => {
    setSubmitting(true);
    try {
      const payload = { ...form };
      // strip empties so backend doesn't store ""
      Object.keys(payload).forEach((k) => {
        if (payload[k] === "" || payload[k] === null) delete payload[k];
      });
      const r = await api.post("/clients", payload);
      toast({ title: `Client created · MRN ${r.data.mrn || r.data.id.slice(0, 8)}` });
      onCreated && onCreated(r.data);
      reset();
      onOpenChange(false);
    } catch (e) {
      toast({ title: "Failed to create client", description: e?.response?.data?.detail || "" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset(); }}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Add new client</DialogTitle>
          <DialogDescription>Complete the four steps to create the client record.</DialogDescription>
        </DialogHeader>

        {/* Step indicator */}
        <div className="flex items-center justify-between border-b border-[#e7dfc9] pb-4 mb-2" data-testid="wizard-stepper">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const active = i === step;
            const done = i < step;
            return (
              <div key={s.key} className="flex-1 flex items-center">
                <div
                  className={`flex flex-col items-center gap-1 flex-1 ${active || done ? "text-[#2f4a3a]" : "text-[#8a8a8a]"}`}
                >
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs ${
                    done ? "bg-[#2f4a3a] text-[#f6f1e6]" :
                    active ? "border-2 border-[#c19a4b] bg-[#fbf7ee] text-[#8a6a3c]" :
                    "border border-[#e0d6bc] bg-[#f6f1e6]"
                  }`}>
                    {done ? <CheckCircle2 size={14} /> : <Icon size={14} />}
                  </div>
                  <span className="text-[10px] uppercase tracking-wider hidden sm:block">{s.label}</span>
                </div>
                {i < STEPS.length - 1 && <div className={`h-px flex-1 ${i < step ? "bg-[#2f4a3a]" : "bg-[#e0d6bc]"}`} />}
              </div>
            );
          })}
        </div>

        <div className="max-h-[55vh] overflow-y-auto pr-1">
          {step === 0 && (
            <div className="grid sm:grid-cols-2 gap-4" data-testid="wizard-step-demographics">
              <div className="sm:col-span-2"><Label>Full legal name *</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.full_name} onChange={(e) => set({ full_name: e.target.value })} data-testid="wiz-fullname" />
              </div>
              <div><Label>Date of birth</Label>
                <Input type="date" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.dob} onChange={(e) => set({ dob: e.target.value })} data-testid="wiz-dob" />
              </div>
              <div><Label>Sex assigned at birth</Label>
                <Select value={form.sex} onValueChange={(v) => set({ sex: v })}>
                  <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="female">Female</SelectItem>
                    <SelectItem value="male">Male</SelectItem>
                    <SelectItem value="intersex">Intersex</SelectItem>
                    <SelectItem value="undisclosed">Prefer not to say</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div><Label>Gender identity</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" placeholder="e.g. Woman, Non-binary" value={form.gender_identity} onChange={(e) => set({ gender_identity: e.target.value })} />
              </div>
              <div><Label>Pronouns</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" placeholder="she/her, they/them…" value={form.pronouns} onChange={(e) => set({ pronouns: e.target.value })} />
              </div>
              <div><Label>Preferred language</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.language} onChange={(e) => set({ language: e.target.value })} />
              </div>
              <div><Label>Marital status</Label>
                <Select value={form.marital_status} onValueChange={(v) => set({ marital_status: v })}>
                  <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="single">Single</SelectItem>
                    <SelectItem value="married">Married</SelectItem>
                    <SelectItem value="partnered">Partnered</SelectItem>
                    <SelectItem value="divorced">Divorced</SelectItem>
                    <SelectItem value="widowed">Widowed</SelectItem>
                    <SelectItem value="undisclosed">Prefer not to say</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="grid sm:grid-cols-2 gap-4" data-testid="wizard-step-contact">
              <div><Label>Email</Label>
                <Input type="email" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.email} onChange={(e) => set({ email: e.target.value })} data-testid="wiz-email" />
              </div>
              <div><Label>Mobile phone</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.phone} onChange={(e) => set({ phone: e.target.value })} data-testid="wiz-phone" />
              </div>
              <div><Label>Alternate phone</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.alt_phone} onChange={(e) => set({ alt_phone: e.target.value })} />
              </div>
              <div className="sm:col-span-2"><Label>Address</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.address} onChange={(e) => set({ address: e.target.value })} placeholder="Street, City, State, ZIP" />
              </div>
              <div className="sm:col-span-2"><Label>Emergency contact</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.emergency_contact} onChange={(e) => set({ emergency_contact: e.target.value })} placeholder="Name · relationship · phone" />
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="grid sm:grid-cols-2 gap-4" data-testid="wizard-step-wellness">
              <div className="sm:col-span-2"><Label>Primary concern / reason for visit</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.primary_concern} onChange={(e) => set({ primary_concern: e.target.value })} data-testid="wiz-primary-concern" />
              </div>
              <div className="sm:col-span-2"><Label>Wellness goals</Label>
                <textarea rows={2} className="mt-2 w-full bg-[#f6f1e6] border border-[#e0d6bc] rounded-md p-2 text-sm" value={form.wellness_goals} onChange={(e) => set({ wellness_goals: e.target.value })} />
              </div>
              <div><Label>Current supplements / medications</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.current_supplements} onChange={(e) => set({ current_supplements: e.target.value })} />
              </div>
              <div><Label>Allergies</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.allergies} onChange={(e) => set({ allergies: e.target.value })} />
              </div>
              <div><Label>Dietary restrictions</Label>
                <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.dietary_restrictions} onChange={(e) => set({ dietary_restrictions: e.target.value })} />
              </div>
              <div><Label>Referral source</Label>
                <Select value={form.referral_source} onValueChange={(v) => set({ referral_source: v })}>
                  <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue placeholder="How did they find us?" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="google">Google search</SelectItem>
                    <SelectItem value="instagram">Instagram</SelectItem>
                    <SelectItem value="facebook">Facebook</SelectItem>
                    <SelectItem value="referral">Friend / family referral</SelectItem>
                    <SelectItem value="provider_referral">Provider referral</SelectItem>
                    <SelectItem value="event">Event / fair</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="grid gap-4" data-testid="wizard-step-consent">
              <div><Label>Preferred communication channel</Label>
                <Select value={form.comms_pref} onValueChange={(v) => set({ comms_pref: v })}>
                  <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="email">Email</SelectItem>
                    <SelectItem value="sms">SMS</SelectItem>
                    <SelectItem value="phone">Phone call</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Toggle label="Consent to telehealth visits" checked={form.consent_telehealth} onChange={(v) => set({ consent_telehealth: v })} testid="wiz-consent-telehealth" />
              <Toggle label="Consent to be photographed for chart documentation" checked={form.consent_photo} onChange={(v) => set({ consent_photo: v })} />
              <Toggle label="Opt-in to wellness updates and promotions" checked={form.consent_marketing} onChange={(v) => set({ consent_marketing: v })} />
              <div><Label>Internal notes</Label>
                <textarea rows={3} className="mt-2 w-full bg-[#f6f1e6] border border-[#e0d6bc] rounded-md p-2 text-sm" value={form.notes} onChange={(e) => set({ notes: e.target.value })} placeholder="Visible to staff only" />
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between pt-4 border-t border-[#e7dfc9]">
          <Button variant="outline" onClick={back} disabled={step === 0} className="rounded-full">
            <ChevronLeft size={14} className="mr-1" /> Back
          </Button>
          <span className="text-xs text-[#6a6a6a]">Step {step + 1} of {STEPS.length}</span>
          {step < STEPS.length - 1 ? (
            <Button onClick={next} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="wiz-next-btn">
              Next <ChevronRight size={14} className="ml-1" />
            </Button>
          ) : (
            <Button onClick={submit} disabled={submitting} className="rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]" data-testid="wiz-create-btn">
              {submitting ? "Creating…" : "Create client"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Toggle({ label, checked, onChange, testid }) {
  return (
    <label className="flex items-center gap-3 cursor-pointer">
      <input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} data-testid={testid} />
      <span className="text-sm text-[#1f2a22]">{label}</span>
    </label>
  );
}
