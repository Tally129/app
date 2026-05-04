import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useToast } from "../../hooks/use-toast";
import { useAuth } from "../../lib/auth";
import { ShieldCheck, ShieldOff, KeyRound } from "lucide-react";

export default function Security() {
  const { user, refreshMe } = useAuth();
  const { toast } = useToast();
  const [setup, setSetup] = React.useState(null);
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const startSetup = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/auth/mfa/setup");
      setSetup(data);
    } catch {
      toast({ title: "Could not start MFA setup" });
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true);
    try {
      await api.post("/auth/mfa/verify", { token: code });
      toast({ title: "Two-factor enabled" });
      setSetup(null);
      setCode("");
      await refreshMe();
    } catch (e) {
      toast({ title: "Invalid code", description: e?.response?.data?.detail || "Try again." });
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      await api.post("/auth/mfa/disable");
      toast({ title: "Two-factor disabled" });
      await refreshMe();
    } catch {
      toast({ title: "Failed to disable" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Security"
        subtitle="Two-factor authentication strengthens your portal sign-in."
      />

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 max-w-2xl">
        <div className="flex items-center gap-3">
          {user?.mfa_enabled ? (
            <ShieldCheck className="text-[#2f4a3a]" />
          ) : (
            <ShieldOff className="text-[#8a6a3c]" />
          )}
          <div>
            <div className="font-medium">Two-factor authentication</div>
            <div className="text-sm text-[#6a6a6a]">
              Status: {user?.mfa_enabled ? "Enabled" : "Disabled"}
            </div>
          </div>
        </div>

        {!user?.mfa_enabled && !setup && (
          <Button
            onClick={startSetup}
            disabled={busy}
            className="mt-5 btn-lift h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
          >
            <KeyRound size={16} className="mr-2" /> Set up authenticator app
          </Button>
        )}

        {setup && (
          <div className="mt-5 space-y-4">
            <p className="text-sm text-[#3a3a3a]">
              Open your authenticator app (Google Authenticator, Authy, 1Password) and add a new account with this secret:
            </p>
            <div className="font-mono text-sm bg-[#f6f1e6] border border-[#e0d6bc] rounded-lg px-3 py-2 break-all">
              {setup.secret}
            </div>
            <p className="text-xs text-[#6a6a6a] break-all">
              Or use provisioning URI: {setup.provisioning_uri}
            </p>
            <div>
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="6-digit code"
                maxLength={6}
                className="bg-[#f6f1e6] border-[#e0d6bc] max-w-xs"
              />
            </div>
            <Button
              onClick={verify}
              disabled={busy || code.length < 6}
              className="btn-lift h-11 rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"
            >
              Verify & enable
            </Button>
          </div>
        )}

        {user?.mfa_enabled && (
          <Button
            onClick={disable}
            disabled={busy}
            variant="outline"
            className="mt-5 btn-lift h-11 rounded-full border-[#7a2a2a] text-[#7a2a2a] bg-transparent hover:bg-[#7a2a2a] hover:text-[#f6f1e6]"
          >
            Disable two-factor
          </Button>
        )}
      </div>
    </PortalLayout>
  );
}
