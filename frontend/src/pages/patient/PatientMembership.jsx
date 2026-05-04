import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { Crown, CheckCircle2 } from "lucide-react";

const TIERS = [
  { id: "essentials", name: "Essentials Wellness", price: 99, perks: ["1 consult / month", "Seasonal detox guidance", "10% off supplements"] },
  { id: "core", name: "Core Wellness", price: 199, perks: ["Advanced consult + lab review", "Hormone or thyroid panel quarterly", "15% off"], featured: true },
  { id: "vip", name: "VIP Wellness", price: 299, perks: ["2 consults / month", "Thermography + IV drip", "20% off"] },
];

export default function PatientMembership() {
  const { toast } = useToast();
  const [me, setMe] = React.useState(null);
  const [tier, setTier] = React.useState("core");
  const [method, setMethod] = React.useState("chase_pos");

  const load = () => api.get("/memberships/mine").then((r) => setMe(r.data));
  React.useEffect(() => { load(); }, []);

  const join = async () => {
    try {
      await api.post("/memberships", { tier, billing_method: method });
      toast({ title: "Welcome!", description: method === "stripe" ? "Stripe integration will be activated once API key is set." : "Please complete payment in-office via Chase POS." });
      load();
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
  };

  return (
    <PortalLayout>
      <PortalHeader title="Membership" subtitle="Monthly wellness care, your way." />

      {me ? (
        <div className="rounded-3xl border border-[#c19a4b] bg-[#fbf2d9] p-6 mb-6">
          <div className="flex items-center gap-3">
            <Crown className="text-[#c19a4b]" />
            <div>
              <div className="font-display text-2xl text-[#1f2a22] capitalize">{me.tier} Wellness</div>
              <div className="text-sm text-[#6a6a6a]">${me.price}/mo · {me.billing_method.replace("_", " ")} · {me.status}</div>
              {me.next_bill_date && <div className="text-xs text-[#8a6a3c] mt-1">Next bill: {new Date(me.next_bill_date).toLocaleDateString()}</div>}
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 mb-6 text-[#6a6a6a] text-sm">
          You don’t have an active membership. Choose a tier below to get started.
        </div>
      )}

      {!me && (
        <>
          <div className="grid md:grid-cols-3 gap-4 mb-6">
            {TIERS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTier(t.id)}
                className={`card-hover rounded-2xl border p-6 text-left transition ${tier === t.id ? "border-[#2f4a3a] ring-2 ring-[#2f4a3a]/30 bg-[#fbf7ee]" : "border-[#e7dfc9] bg-[#fbf7ee]"}`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-display text-xl text-[#1f2a22]">{t.name}</div>
                  {tier === t.id && <CheckCircle2 className="text-[#2f4a3a]" size={18} />}
                </div>
                <div className="mt-1 text-[#2f4a3a] font-display text-2xl">${t.price}<span className="text-sm text-[#6a6a6a]">/mo</span></div>
                <ul className="mt-3 space-y-1 text-sm text-[#3a3a3a]">
                  {t.perks.map((p) => <li key={p} className="flex items-start gap-2"><CheckCircle2 size={14} className="mt-0.5 text-[#2f4a3a]" />{p}</li>)}
                </ul>
              </button>
            ))}
          </div>

          <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 max-w-lg">
            <Label>Billing method</Label>
            <Select value={method} onValueChange={setMethod}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="chase_pos">In-office (Chase POS) — pay at visit</SelectItem>
                <SelectItem value="stripe">Online (Stripe) — auto-bill monthly</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-[#6a6a6a] mt-2">
              Stripe auto-bill requires an API key; until configured, online signup is recorded and marked pending.
            </p>
            <Button onClick={join} className="mt-4 btn-lift rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">Start membership</Button>
          </div>
        </>
      )}
    </PortalLayout>
  );
}
