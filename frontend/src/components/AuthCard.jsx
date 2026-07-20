import React from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import Logo from "./Logo";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { ArrowLeft, Shield } from "lucide-react";
import { useToast } from "../hooks/use-toast";
import { useAuth, roleHome, isWorkforceRole } from "../lib/auth";
import { getErrorMessage } from "../lib/errors";

/**
 * Shared authentication shell used by both the Patient Portal (`/login`) and
 * the Staff & Provider Portal (`/staff-login`).
 *
 * Both pages render an identical layout, typography, spacing, branding and
 * animations — the only differences are the title, subtitle, the cross-portal
 * link at the bottom, and (for the Google Emergent flow) which URL the OAuth
 * provider redirects back to.
 *
 * All authentication logic — email/password login, MFA challenge, Google OAuth
 * (both Emergent-managed and direct backend flows), workforce vs. client
 * routing — is centralized here so the two portals cannot drift apart.
 */
export default function AuthCard({
  variant,          // "patient" | "staff"
  title,
  subtitle,
  crossPortalTo,    // where to send a user who chose the "wrong" portal link
  crossPortalLabel,
  crossPortalLinkText,
  redirectPath,     // where the Emergent OAuth flow returns to (usually this page)
}) {
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const {
    loginWithPassword, loginWithGoogleSession, beginGoogleOAuthDirect,
  } = useAuth();

  const [form, setForm] = React.useState(() => {
    let last = "";
    try { last = localStorage.getItem("nms_last_login_email") || ""; } catch {}
    return { email: last, password: "", mfa: "" };
  });
  const [mfaRequired, setMfaRequired] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));
  const from = location.state?.from;

  const finishLogin = React.useCallback((res) => {
    const role = res.user.role;
    const belongsHere =
      (variant === "staff" && isWorkforceRole(role)) ||
      (variant === "patient" && !isWorkforceRole(role));
    try { localStorage.setItem("nms_last_login_email", form.email); } catch {}
    if (!belongsHere) {
      const other = isWorkforceRole(role) ? "staff workspace" : "patient portal";
      toast({ title: "Welcome back", description: `Redirecting you to your ${other}…` });
      navigate(roleHome(role), { replace: true });
      return;
    }
    toast({ title: "Welcome back" });
    navigate(from || roleHome(role), { replace: true });
  }, [variant, form.email, from, navigate, toast]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.email || !form.password) {
      toast({ title: "Enter your email and password" });
      return;
    }
    setBusy(true);
    try {
      const res = await loginWithPassword(form.email, form.password, form.mfa || undefined);
      if (res.mfa_required) {
        setMfaRequired(true);
        toast({ title: "Two-factor required", description: "Enter the 6-digit code from your authenticator app." });
        return;
      }
      finishLogin(res);
    } catch (err) {
      toast({ title: "Sign in failed", description: getErrorMessage(err) || "Please try again." });
    } finally { setBusy(false); }
  };

  // --- Google: Emergent-managed by default; use direct backend flow if wired.
  const [googleDirectOn, setGoogleDirectOn] = React.useState(false);
  React.useEffect(() => {
    import("../lib/api").then(({ api }) =>
      api.get("/health")
        .then((r) => setGoogleDirectOn(Boolean(r.data?.integrations?.google_oauth_direct)))
        .catch(() => setGoogleDirectOn(false)),
    );
  }, []);

  const googleSignInEmergent = () => {
    const redirect = `${window.location.origin}${redirectPath || "/login"}`;
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirect)}`;
  };
  const googleSignInDirect = async () => {
    try {
      await beginGoogleOAuthDirect();
    } catch (e) {
      toast({ title: "Google sign-in unavailable", description: getErrorMessage(e) || e.message });
    }
  };

  // Handle Emergent Google callback: `#session_id=...` fragment.
  React.useEffect(() => {
    const hash = window.location.hash || "";
    const m = hash.match(/session_id=([^&]+)/);
    if (!m) return;
    (async () => {
      try {
        const res = await loginWithGoogleSession(m[1]);
        window.history.replaceState({}, document.title, window.location.pathname);
        finishLogin(res);
      } catch (err) {
        toast({ title: "Google sign-in failed", description: getErrorMessage(err) || "Try email sign-in instead." });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="page-fade min-h-screen bg-gradient-to-b from-white via-[#f4f7f2] to-[#eef3ec] font-body" data-testid={`${variant}-login-page`}>
      <div className="h-1 w-full bg-gradient-to-r from-[#7fa48b] via-[#c19a4b] to-[#7fa48b]" />

      <div className="max-w-md mx-auto px-6 pt-8">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-[#2f6a4a] transition-colors">
          <ArrowLeft size={16} /> Back to home
        </Link>
      </div>

      <section className="max-w-md mx-auto px-6 mt-6 text-center animate-[fadeIn_.35s_ease-out]">
        <div className="flex justify-center">
          <div className="rounded-full bg-white shadow-sm border border-[#e2ebe4] p-2">
            <Logo size={72} />
          </div>
        </div>
        <div className="inline-flex items-center gap-1.5 mt-6 px-3 py-1 rounded-full bg-[#eaf2ec] border border-[#cfe0d3] text-[11px] tracking-widest uppercase text-[#3d6b52]">
          <Shield size={11} /> {variant === "staff" ? "Secure staff access" : "Secure patient access"}
        </div>
        <h1
          className="font-display text-[36px] sm:text-[40px] text-[#1f2a22] mt-4 leading-tight"
          data-testid={`${variant}-login-title`}
        >
          {title}
        </h1>
        <p className="text-slate-500 mt-2 text-sm">{subtitle}</p>
      </section>

      <section className="max-w-md mx-auto px-6 mt-8 pb-10">
        <div className="rounded-3xl border border-[#e2ebe4] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_10px_30px_-15px_rgba(47,106,74,0.15)] p-7 sm:p-8 animate-[fadeIn_.45s_ease-out]">
          <Button
            type="button"
            data-testid={`${variant}-google-sso`}
            onClick={googleDirectOn ? googleSignInDirect : googleSignInEmergent}
            variant="outline"
            className="btn-lift h-11 w-full rounded-full border-[#cfe0d3] bg-white text-slate-700 hover:bg-[#f6faf7] hover:border-[#7fa48b] transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 48 48" className="mr-2">
              <path fill="#FFC107" d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12s5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24s8.955,20,20,20s20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"/>
              <path fill="#FF3D00" d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"/>
              <path fill="#4CAF50" d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"/>
              <path fill="#1976D2" d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"/>
            </svg>
            Continue with Google
          </Button>

          <div className="flex items-center gap-3 my-5">
            <div className="flex-1 h-px bg-[#e2ebe4]" />
            <span className="text-[11px] tracking-widest uppercase text-slate-400">or</span>
            <div className="flex-1 h-px bg-[#e2ebe4]" />
          </div>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <Label htmlFor={`${variant}-email`} className="text-slate-700">Email</Label>
              <Input
                id={`${variant}-email`} type="email" autoComplete="email" required
                value={form.email} onChange={(e) => set("email", e.target.value)}
                className="mt-2 h-11 bg-white border-[#d9e2db] focus-visible:border-[#7fa48b] focus-visible:ring-[#7fa48b]/30 rounded-lg"
                data-testid={`${variant}-login-email`}
              />
            </div>
            <div>
              <Label htmlFor={`${variant}-password`} className="text-slate-700">Password</Label>
              <Input
                id={`${variant}-password`} type="password" autoComplete="current-password" required
                value={form.password} onChange={(e) => set("password", e.target.value)}
                className="mt-2 h-11 bg-white border-[#d9e2db] focus-visible:border-[#7fa48b] focus-visible:ring-[#7fa48b]/30 rounded-lg"
                data-testid={`${variant}-login-password`}
              />
            </div>
            {mfaRequired && (
              <div className="animate-[fadeIn_.25s_ease-out]">
                <Label htmlFor={`${variant}-mfa`} className="text-slate-700">Two-factor code</Label>
                <Input
                  id={`${variant}-mfa`} value={form.mfa} onChange={(e) => set("mfa", e.target.value)}
                  className="mt-2 h-11 bg-white border-[#d9e2db] focus-visible:border-[#7fa48b] focus-visible:ring-[#7fa48b]/30 rounded-lg tracking-[0.3em] font-mono"
                  placeholder="6-digit code" maxLength={6}
                  data-testid={`${variant}-login-mfa`}
                />
              </div>
            )}
            <Button
              type="submit" disabled={busy}
              className="btn-lift h-12 w-full rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white shadow-sm transition-all"
              data-testid={`${variant}-login-submit`}
            >
              {busy ? "Signing in…" : mfaRequired ? "Verify & sign in" : "Sign in"}
            </Button>
          </form>

          {variant === "patient" && (
            <p className="text-center text-sm text-slate-500 mt-5">
              New here?{" "}
              <Link to="/signup" className="text-[#2f6a4a] hover:text-[#1f4a34] underline underline-offset-2 font-medium" data-testid="signup-link">
                Create an account
              </Link>
            </p>
          )}

          <p className="text-center text-[12px] text-slate-500 mt-4">
            {crossPortalLabel}{" "}
            <Link
              to={crossPortalTo}
              className="text-[#2f6a4a] hover:text-[#1f4a34] underline underline-offset-2 font-medium"
              data-testid={variant === "patient" ? "staff-login-link" : "patient-login-link"}
            >
              {crossPortalLinkText}
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
