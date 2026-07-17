import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { Save, KeyRound, Download, ShieldCheck } from "lucide-react";

export default function MyAccount() {
  const { user, refreshMe } = useAuth();
  const { toast } = useToast();
  const [profile, setProfile] = React.useState({ full_name: "", phone: "" });
  const [pw, setPw] = React.useState({ current_password: "", new_password: "", confirm: "" });
  const [savingProfile, setSavingProfile] = React.useState(false);
  const [savingPw, setSavingPw] = React.useState(false);

  React.useEffect(() => {
    if (user) setProfile({ full_name: user.full_name || "", phone: user.phone || "" });
  }, [user]);

  const saveProfile = async () => {
    setSavingProfile(true);
    try {
      await api.put("/auth/me", profile);
      toast({ title: "Profile updated" });
      if (refreshMe) await refreshMe();
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    } finally {
      setSavingProfile(false);
    }
  };

  const savePw = async () => {
    if (pw.new_password.length < 8) {
      toast({ title: "Password must be 8+ characters" });
      return;
    }
    if (pw.new_password !== pw.confirm) {
      toast({ title: "Passwords do not match" });
      return;
    }
    setSavingPw(true);
    try {
      await api.post("/auth/change-password", {
        current_password: pw.current_password,
        new_password: pw.new_password,
      });
      toast({ title: "Password changed" });
      setPw({ current_password: "", new_password: "", confirm: "" });
    } catch (e) {
      toast({ title: "Failed", description: e?.response?.data?.detail || "" });
    } finally {
      setSavingPw(false);
    }
  };

  return (
    <PortalLayout>
      <PortalHeader title="My Account" subtitle="Manage your profile and password" />

      <div className="grid md:grid-cols-2 gap-6">
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6" data-testid="profile-card">
          <div className="eyebrow text-[#8a6a3c] mb-4">Profile</div>
          <div className="space-y-4">
            <div>
              <Label>Email</Label>
              <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={user?.email || ""} disabled data-testid="account-email-input" />
            </div>
            <div>
              <Label>Full name</Label>
              <Input
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                value={profile.full_name}
                onChange={(e) => setProfile({ ...profile, full_name: e.target.value })}
                data-testid="account-fullname-input"
              />
            </div>
            <div>
              <Label>Phone</Label>
              <Input
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                value={profile.phone}
                onChange={(e) => setProfile({ ...profile, phone: e.target.value })}
                data-testid="account-phone-input"
              />
            </div>
            <div>
              <Label>Role</Label>
              <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={user?.role || ""} disabled />
            </div>
            <Button
              onClick={saveProfile}
              disabled={savingProfile}
              className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
              data-testid="account-save-profile-btn"
            >
              <Save size={16} className="mr-2" />
              {savingProfile ? "Saving…" : "Save profile"}
            </Button>
          </div>
        </div>

        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6" data-testid="password-card">
          <div className="eyebrow text-[#8a6a3c] mb-4">Change password</div>
          <div className="space-y-4">
            <div>
              <Label>Current password</Label>
              <Input
                type="password"
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                value={pw.current_password}
                onChange={(e) => setPw({ ...pw, current_password: e.target.value })}
                data-testid="account-current-password-input"
              />
            </div>
            <div>
              <Label>New password (12+ chars, cannot contain your name/email, no common passwords)</Label>
              <Input
                type="password"
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                value={pw.new_password}
                onChange={(e) => setPw({ ...pw, new_password: e.target.value })}
                data-testid="account-new-password-input"
              />
            </div>
            <div>
              <Label>Confirm new password</Label>
              <Input
                type="password"
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                value={pw.confirm}
                onChange={(e) => setPw({ ...pw, confirm: e.target.value })}
                data-testid="account-confirm-password-input"
              />
            </div>
            <Button
              onClick={savePw}
              disabled={savingPw}
              className="btn-lift rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"
              data-testid="account-save-password-btn"
            >
              <KeyRound size={16} className="mr-2" />
              {savingPw ? "Saving…" : "Update password"}
            </Button>
          </div>
        </div>
      </div>

      {user?.role === "client" && <MyDataExportCard />}
    </PortalLayout>
  );
}

function MyDataExportCard() {
  const { toast } = useToast();
  const [busy, setBusy] = React.useState(false);
  const [disclosuresBusy, setDisclosuresBusy] = React.useState(false);
  const downloadJson = async () => {
    setBusy(true);
    try {
      const r = await api.post("/patient/data-export");
      const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `natmedsol-my-record-${new Date().toISOString().slice(0,10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast({ title: "Downloaded", description: "Under HIPAA §164.524 you have the right to a copy of your record." });
    } catch (e) { toast({ title: "Export failed", description: e?.response?.data?.detail || "" }); }
    finally { setBusy(false); }
  };
  const downloadDisclosures = async () => {
    setDisclosuresBusy(true);
    try {
      const me = await api.get("/clients/me");
      if (!me.data?.id) throw new Error("no client record");
      const r = await api.get(`/clients/${me.data.id}/disclosures`);
      const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `natmedsol-disclosures-${new Date().toISOString().slice(0,10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast({ title: "Downloaded", description: "Accounting of disclosures under HIPAA §164.528." });
    } catch (e) { toast({ title: "Failed", description: e?.response?.data?.detail || "" }); }
    finally { setDisclosuresBusy(false); }
  };
  return (
    <div className="mt-8 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6" data-testid="my-data-export-card">
      <h2 className="font-display text-2xl text-[#1f2a22] inline-flex items-center gap-2"><ShieldCheck size={18} className="text-[#2f4a3a]" /> My data &amp; privacy</h2>
      <p className="text-sm text-[#5a5a5a] mt-1">Exercise your HIPAA rights — download a copy of everything we store about you, or see who has accessed your record.</p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Button onClick={downloadJson} disabled={busy} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="my-data-download-btn">
          <Download size={14} className="mr-2" /> {busy ? "Preparing…" : "Download my record (JSON)"}
        </Button>
        <Button onClick={downloadDisclosures} disabled={disclosuresBusy} variant="outline" className="rounded-full border-[#c19a4b] text-[#8a6a3c]" data-testid="my-disclosures-btn">
          <Download size={14} className="mr-2" /> {disclosuresBusy ? "Preparing…" : "Accounting of disclosures"}
        </Button>
      </div>
    </div>
  );
}
