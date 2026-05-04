import React from "react";
import { Link, useNavigate } from "react-router-dom";
import Logo from "../components/Logo";
import Footer from "../components/Footer";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { ArrowLeft } from "lucide-react";
import { useToast } from "../hooks/use-toast";
import { LS_KEYS } from "../mock";

export default function Login() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [form, setForm] = React.useState({ email: "", password: "" });
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const submit = (e) => {
    e.preventDefault();
    if (!form.email || !form.password) {
      toast({ title: "Enter your email and password" });
      return;
    }
    localStorage.setItem(LS_KEYS.session, JSON.stringify({ email: form.email }));
    toast({ title: "Welcome back" });
    navigate("/");
  };

  const googleSignIn = () => {
    toast({ title: "Google sign-in coming soon", description: "For now please use email sign-in." });
  };

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
        <h1 className="font-display text-[40px] text-[#1f2a22] mt-8">Patient Sign In</h1>
        <p className="text-[#5a5a5a] mt-2 text-sm">Access your records and manage upcoming visits.</p>
      </section>

      <section className="max-w-md mx-auto px-6 mt-8">
        <div className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-8">
          <Button
            type="button"
            onClick={googleSignIn}
            variant="outline"
            className="btn-lift h-11 w-full rounded-full border-[#e0d6bc] bg-[#fbf7ee] text-[#3a3a3a] hover:bg-[#f1ead8]"
          >
            <svg width="16" height="16" viewBox="0 0 48 48" className="mr-2">
              <path fill="#FFC107" d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12 s5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24s8.955,20,20,20 s20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"/>
              <path fill="#FF3D00" d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039 l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"/>
              <path fill="#4CAF50" d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36 c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"/>
              <path fill="#1976D2" d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571 c0.001-0.001,0.002-0.001,0.003-0.002l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"/>
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
                className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" required />
            </div>
            <div>
              <Label htmlFor="password" className="text-[#3a3a3a]">Password</Label>
              <Input id="password" type="password" value={form.password} onChange={(e) => set("password", e.target.value)}
                className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" required />
            </div>
            <Button type="submit" className="btn-lift h-12 w-full rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
              Sign In
            </Button>
          </form>

          <p className="text-center text-sm text-[#6a6a6a] mt-5">
            New here?{" "}
            <Link to="/signup" className="text-[#2f4a3a] underline underline-offset-2">Create an account</Link>
          </p>
        </div>
      </section>
      <Footer />
    </div>
  );
}
