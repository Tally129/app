import React from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import Logo from "../components/Logo";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { useAuth, roleHome } from "../lib/auth";
import { useToast } from "../hooks/use-toast";
import { Lock, Briefcase, ArrowRight, Building2 } from "lucide-react";

/**
 * Dedicated staff sign-in. Same backend as /login — cosmetic landing only.
 * Uses a darker, "back-of-house" aesthetic to differentiate from the patient/marketing site.
 */
export default function StaffLogin() {
  const { loginWithPassword, user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = React.useState(() => {
    try { return localStorage.getItem("nms_last_login_email") || ""; } catch { return ""; }
  });
  const [password, setPassword] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const from = location.state?.from?.pathname;

  React.useEffect(() => {
    if (user) navigate(from || roleHome(user.role), { replace: true });
  }, [user, from, navigate]);

  const submit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await loginWithPassword(email, password);
      try { localStorage.setItem("nms_last_login_email", email); } catch {}
      if (res.user.role === "client") {
        toast({ title: "Heads up", description: "This is the staff portal — your client account opens the patient view." });
      }
      navigate(roleHome(res.user.role), { replace: true });
    } catch (err) {
      toast({ title: "Sign-in failed", description: err?.response?.data?.detail || "Check your email and password." });
    } finally { setSubmitting(false); }
  };

  return (
    <div className="min-h-screen bg-[#0e1a14] text-[#f6f1e6] flex flex-col" data-testid="staff-login-page">
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <div className="flex flex-col items-center gap-3 mb-8">
            <div className="rounded-full bg-[#2f4a3a] p-3 border border-[#c19a4b]">
              <Briefcase size={22} className="text-[#c19a4b]" />
            </div>
            <Logo size={64} withText={false} />
            <h1 className="font-display text-3xl text-[#f6f1e6]" data-testid="staff-login-title">Staff sign in</h1>
            <p className="text-sm text-[#8a9a8e] text-center">
              Front desk · practitioners · admins. Clients should use the{" "}
              <Link to="/login" className="text-[#c19a4b] underline">patient portal</Link>.
            </p>
          </div>

          <form onSubmit={submit} className="rounded-2xl border border-[#2f4a3a] bg-[#1a2a22] p-7 space-y-4">
            <div>
              <Label className="text-[#c8d4cc]">Email</Label>
              <Input
                type="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)}
                className="mt-2 bg-[#0e1a14] border-[#2f4a3a] text-[#f6f1e6] placeholder:text-[#5a6a5e]"
                placeholder="you@natmedsol.local"
                data-testid="staff-login-email"
                required
              />
            </div>
            <div>
              <Label className="text-[#c8d4cc]">Password</Label>
              <Input
                type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="mt-2 bg-[#0e1a14] border-[#2f4a3a] text-[#f6f1e6]"
                data-testid="staff-login-password"
                required
              />
            </div>
            <Button
              type="submit" disabled={submitting}
              className="w-full h-11 rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22] btn-lift"
              data-testid="staff-login-submit"
            >
              <Lock size={14} className="mr-2" /> {submitting ? "Signing in…" : "Sign in"} <ArrowRight size={14} className="ml-2" />
            </Button>
          </form>

          <div className="mt-6 text-center">
            <Link to="/" className="text-xs text-[#8a9a8e] hover:text-[#c19a4b] inline-flex items-center gap-1">
              <Building2 size={11} /> Back to natmedsol.com
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
