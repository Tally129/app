import React from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import Logo from "../components/Logo";
import Footer from "../components/Footer";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { ArrowLeft } from "lucide-react";
import { useToast } from "../hooks/use-toast";
import { useAuth, roleHome } from "../lib/auth";
import { getErrorMessage } from "../lib/errors";

export default function Login() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { loginWithPassword } = useAuth();
  const [form, setForm] = React.useState(() => {
    // Pre-fill the last successful login email saved on this device
    let last = "";
    try { last = localStorage.getItem("nms_last_login_email") || ""; } catch {}
    return { email: last, password: "", mfa: "" };
  });
  const [mfaRequired, setMfaRequired] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

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
      const dest = location.state?.from || roleHome(res.user.role);
      try { localStorage.setItem("nms_last_login_email", form.email); } catch {}
      toast({ title: "Welcome back" });
      navigate(dest, { replace: true });
    } catch (err) {
      toast({
        title: "Sign in failed",
        description: getErrorMessage(err) || "Please try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  const googleSignIn = () => {
    // Emergent-managed Google Auth: redirect to provider, returns to /login#session_id=...
    const redirect = `${window.location.origin}/login`;
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirect)}`;
  };

  // If backend has direct Google OAuth wired (client_id/secret env vars set), use that instead.
  const [googleDirectOn, setGoogleDirectOn] = React.useState(false);
  React.useEffect(() => {
    import("../lib/api").then(({ api }) =>
      api.get("/health")
        .then((r) => setGoogleDirectOn(Boolean(r.data?.integrations?.google_oauth_direct)))
        .catch(() => setGoogleDirectOn(false)),
    );
  }, []);
  const { beginGoogleOAuthDirect } = useAuth();
  const googleSignInDirect = async () => {
    try {
      await beginGoogleOAuthDirect();
    } catch (e) {
      toast({ title: "Google sign-in unavailable", description: getErrorMessage(e) || e.message });
    }
  };

  // Handle Google callback: parse #session_id=... from the URL fragment, exchange for our JWT
  const { loginWithGoogleSession } = useAuth();
  React.useEffect(() => {
    const hash = window.location.hash || "";
    const m = hash.match(/session_id=([^&]+)/);
    if (!m) return;
    (async () => {
      try {
        const res = await loginWithGoogleSession(m[1]);
        // clear the fragment
        window.history.replaceState({}, document.title, window.location.pathname);
        const dest = roleHome(res.user.role);
        toast({ title: "Welcome", description: res.user.email });
        navigate(dest, { replace: true });
      } catch (err) {
        toast({
          title: "Google sign-in failed",
          description: getErrorMessage(err) || "Try email sign-in instead.",
        });
      }
    })();
    // eslint-disable-next-line
  }, []);

  return (
    <div className="page-fade min-h-screen bg-parchment font-body">
      <div className="top-ribbon" />
      <div className="max-w-md mx-auto px-6 pt-10">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-[#6a6a6a] hover:text-[#2f4a3a]">
          <ArrowLeft size={16} /> Back to home
        </Link>
      </div>

      <section className="max-w-md mx-auto px-6 text-center mt-6">
        <div className="flex justify-center"><Logo size={86} /></div>
        <h1 className="font-display text-[40px] text-[#1f2a22] mt-8">Sign in</h1>
        <p className="text-[#5a5a5a] mt-2 text-sm">Clients, practitioners, staff, and admins all sign in here.</p>
      </section>

      <section className="max-w-md mx-auto px-6 mt-8">
        <div className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-8">
          <Button
            type="button"
            data-testid="google-sso-button"
            onClick={googleDirectOn ? googleSignInDirect : googleSignIn}
            variant="outline"
            className="btn-lift h-11 w-full rounded-full border-[#e0d6bc] bg-[#fbf7ee] text-[#3a3a3a] hover:bg-[#f1ead8]"
          >
            <svg width="16" height="16" viewBox="0 0 48 48" className="mr-2">
              <path fill="#FFC107" d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12s5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24s8.955,20,20,20s20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"/>
              <path fill="#FF3D00" d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"/>
              <path fill="#4CAF50" d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"/>
              <path fill="#1976D2" d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"/>
            </svg>
            Sign in with Google
          </Button>

          <div className="flex items-center gap-3 my-5">
            <div className="flex-1 h-px bg-[#e7dfc9]" />
            <span className="text-[11px] tracking-widest uppercase text-[#8a8a8a]">or</span>
            <div className="flex-1 h-px bg-[#e7dfc9]" />
          </div>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <Label htmlFor="email" className="text-[#3a3a3a]">Email</Label>
              <Input id="email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)}
                className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" required autoComplete="email" />
            </div>
            <div>
              <Label htmlFor="password" className="text-[#3a3a3a]">Password</Label>
              <Input id="password" type="password" value={form.password} onChange={(e) => set("password", e.target.value)}
                className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" required autoComplete="current-password" />
            </div>
            {mfaRequired && (
              <div>
                <Label htmlFor="mfa" className="text-[#3a3a3a]">Two-factor code</Label>
                <Input id="mfa" value={form.mfa} onChange={(e) => set("mfa", e.target.value)}
                  className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" placeholder="6-digit code" maxLength={6} />
              </div>
            )}
            <Button type="submit" disabled={busy} className="btn-lift h-12 w-full rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
              {busy ? "Signing in…" : mfaRequired ? "Verify & Sign In" : "Sign In"}
            </Button>
          </form>

          <p className="text-center text-sm text-[#6a6a6a] mt-5">
            New here?{" "}
            <Link to="/signup" className="text-[#2f4a3a] underline underline-offset-2">Create an account</Link>
          </p>
          <p className="text-center text-[11px] text-[#8a8a8a] mt-2">
            Staff: sign in with your issued credentials. Demo: admin@natmedsol.local / Admin!2345
          </p>
        </div>
      </section>
      <Footer />
    </div>
  );
}