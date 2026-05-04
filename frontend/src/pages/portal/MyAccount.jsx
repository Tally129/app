import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { Save, KeyRound } from "lucide-react";

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
              <Label>New password (8+ chars)</Label>
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
    </PortalLayout>
  );
}
