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

export default function Signup() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [form, setForm] = React.useState({ name: "", email: "", phone: "", password: "" });
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const submit = (e) => {
    e.preventDefault();
    if (!form.name || !form.email || !form.password) {
      toast({ title: "Please complete required fields" });
      return;
    }
    const existing = JSON.parse(localStorage.getItem(LS_KEYS.clients) || "[]");
    localStorage.setItem(LS_KEYS.clients, JSON.stringify([...existing, { ...form, ts: Date.now() }]));
    localStorage.setItem(LS_KEYS.session, JSON.stringify({ email: form.email, name: form.name }));
    toast({ title: "Welcome aboard", description: "Your client account has been created." });
    navigate("/");
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
        <h1 className="font-display text-[40px] text-[#1f2a22] mt-8">Create a Client Account</h1>
        <p className="text-[#5a5a5a] mt-2 text-sm">Begin your holistic journey with Natural Medical Solutions.</p>
      </section>

      <section className="max-w-md mx-auto px-6 mt-8">
        <form onSubmit={submit} className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-8 space-y-4">
          <div>
            <Label htmlFor="name" className="text-[#3a3a3a]">Full Name *</Label>
            <Input id="name" value={form.name} onChange={(e) => set("name", e.target.value)}
              className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" required />
          </div>
          <div>
            <Label htmlFor="email" className="text-[#3a3a3a]">Email *</Label>
            <Input id="email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)}
              className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" required />
          </div>
          <div>
            <Label htmlFor="phone" className="text-[#3a3a3a]">Phone</Label>
            <Input id="phone" value={form.phone} onChange={(e) => set("phone", e.target.value)}
              className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" />
          </div>
          <div>
            <Label htmlFor="password" className="text-[#3a3a3a]">Password *</Label>
            <Input id="password" type="password" value={form.password} onChange={(e) => set("password", e.target.value)}
              className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg" required />
          </div>

          <Button type="submit" className="btn-lift h-12 w-full rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
            Create Account
          </Button>

          <p className="text-center text-sm text-[#6a6a6a]">
            Already have an account?{" "}
            <Link to="/login" className="text-[#2f4a3a] underline underline-offset-2">Sign in</Link>
          </p>
        </form>
      </section>
      <Footer />
    </div>
  );
}
