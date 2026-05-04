import React from "react";
import { Link } from "react-router-dom";
import Logo from "../components/Logo";
import Footer from "../components/Footer";
import { heroCopy, membershipTiers, services, testimonials, brand } from "../mock";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { ArrowRight, Check, Leaf, Sparkles, ShieldCheck, Phone, MapPin, Clock } from "lucide-react";
import { useToast } from "../hooks/use-toast";
import { LS_KEYS, hours } from "../mock";

export default function Home() {
  const { toast } = useToast();
  const [vipEmail, setVipEmail] = React.useState("");

  const handleVIPJoin = async (e) => {
    e.preventDefault();
    if (!vipEmail || !vipEmail.includes("@")) {
      toast({ title: "Please enter a valid email", description: "We’ll send your welcome gift there." });
      return;
    }
    try {
      await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/public/vip-signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: vipEmail }),
      });
    } catch {}
    const existing = JSON.parse(localStorage.getItem(LS_KEYS.vip) || "[]");
    localStorage.setItem(LS_KEYS.vip, JSON.stringify([...existing, { email: vipEmail, ts: Date.now() }]));
    setVipEmail("");
    toast({
      title: "Welcome to the VIP list",
      description: "$20 off your first visit is on its way to your inbox.",
    });
  };

  return (
    <div className="page-fade min-h-screen bg-parchment font-body">
      <div className="top-ribbon" />

      {/* HERO */}
      <section className="max-w-5xl mx-auto px-6 pt-16 pb-12 text-center">
        <div className="flex justify-center">
          <Logo size={110} />
        </div>

        <div className="mt-10">
          <p className="eyebrow text-[#8a6a3c]">{heroCopy.eyebrow}</p>
          <h1 className="font-display text-[46px] leading-[1.08] md:text-[64px] text-[#1f2a22] mt-5 max-w-3xl mx-auto">
            {heroCopy.title}
          </h1>
          <p className="mt-5 text-[#5a5a5a] max-w-xl mx-auto leading-relaxed">
            {heroCopy.body}
          </p>
        </div>

        <div className="mt-9 flex flex-col items-center gap-3">
          <Link to="/request-appointment">
            <Button
              className="btn-lift h-12 px-8 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] text-[15px] font-medium"
            >
              Request an Appointment
              <ArrowRight size={18} className="ml-2" />
            </Button>
          </Link>
          <Link to="/login">
            <Button
              variant="outline"
              className="btn-lift h-12 px-8 rounded-full border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#2f4a3a] hover:text-[#f6f1e6] text-[15px] bg-transparent"
            >
              Patient Portal
            </Button>
          </Link>
        </div>

        {/* trust strip */}
        <div className="mt-12 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-[12px] tracking-widest uppercase text-[#8a6a3c]">
          <span className="flex items-center gap-2"><Leaf size={14} /> Root-cause care</span>
          <span className="opacity-40">·</span>
          <span className="flex items-center gap-2"><ShieldCheck size={14} /> Board-certified</span>
          <span className="opacity-40">·</span>
          <span className="flex items-center gap-2"><Sparkles size={14} /> 29+ years of practice</span>
        </div>
      </section>

      {/* TELEHEALTH */}
      <section id="telehealth" className="max-w-6xl mx-auto px-6 mt-10">
        <div className="rounded-3xl bg-[#fbf7ee] border border-[#e7dfc9] p-10 md:p-14 grid md:grid-cols-2 gap-10 items-center">
          <div>
            <p className="eyebrow text-[#8a6a3c]">Now offering</p>
            <h2 className="font-display text-[38px] md:text-[46px] text-[#1f2a22] mt-2 leading-tight">
              Telehealth visits from the comfort of home
            </h2>
            <p className="text-[#5a5a5a] mt-4 leading-relaxed">
              Meet with Dr. Ravello on secure video for consults, follow-ups, lab reviews and protocol updates — wherever you are in Georgia.
            </p>
            <ul className="mt-5 space-y-2 text-sm text-[#3a3a3a]">
              <li className="flex items-start gap-2"><Check size={16} className="mt-0.5 text-[#2f4a3a]" /> HD video with waiting room & in-visit chat</li>
              <li className="flex items-start gap-2"><Check size={16} className="mt-0.5 text-[#2f4a3a]" /> Share labs or images on-screen during your visit</li>
              <li className="flex items-start gap-2"><Check size={16} className="mt-0.5 text-[#2f4a3a]" /> Same personalized protocols, delivered digitally</li>
            </ul>
            <div className="mt-7 flex flex-col sm:flex-row gap-3">
              <Link to="/request-appointment">
                <Button className="btn-lift h-11 px-6 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
                  Book a telehealth visit
                </Button>
              </Link>
              <Link to="/login">
                <Button variant="outline" className="btn-lift h-11 px-6 rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6]">
                  Join from portal
                </Button>
              </Link>
            </div>
          </div>
          <div className="relative">
            <div className="aspect-video rounded-2xl bg-[#2f4a3a] relative overflow-hidden shadow-2xl">
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-24 h-24 rounded-full bg-[#c19a4b]/30 border border-[#c19a4b]/60 flex items-center justify-center">
                  <div className="w-16 h-16 rounded-full bg-[#c19a4b] text-[#1f2a22] flex items-center justify-center">
                    <Leaf size={32} />
                  </div>
                </div>
              </div>
              <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between text-[#f6f1e6] text-xs">
                <span className="px-2 py-1 rounded-full bg-black/30 backdrop-blur">Dr. Ravello</span>
                <span className="px-2 py-1 rounded-full bg-[#2f4a3a] border border-[#c19a4b]">● LIVE</span>
              </div>
            </div>
            <div className="absolute -bottom-4 -right-4 bg-[#fbf7ee] border border-[#e7dfc9] rounded-full px-4 py-2 text-xs tracking-widest uppercase text-[#8a6a3c] shadow-lg">
              Secure · Private · Easy
            </div>
          </div>
        </div>
      </section>

      {/* SERVICES STRIP */}
      <section className="max-w-6xl mx-auto px-6 mt-24">
        <div className="text-center">
          <p className="eyebrow text-[#8a6a3c]">What we offer</p>
          <h2 className="font-display text-[36px] md:text-[44px] text-[#1f2a22] mt-2">Innovative Naturopathic Care</h2>
          <p className="text-[#5a5a5a] max-w-2xl mx-auto mt-3">
            We look at the whole person to get to the root cause — mind, body and spirit. Explore the treatments Dr. Ravello’s team personally curates for you.
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-10">
          {services.map((s) => (
            <Link
              to="/request-appointment"
              key={s.id}
              className="card-hover rounded-xl border border-[#e7dfc9] bg-[#fbf7ee] p-4 text-center text-[13px] text-[#3a3a3a] hover:border-[#c19a4b] hover:text-[#2f4a3a]"
            >
              {s.name}
            </Link>
          ))}
        </div>
      </section>

      {/* DOCTOR BIO */}
      <section className="max-w-5xl mx-auto px-6 mt-24">
        <div className="rounded-3xl bg-[#2f4a3a] text-[#f1ead8] p-10 md:p-14 overflow-hidden relative">
          <div className="absolute -right-10 -top-10 opacity-10">
            <Leaf size={220} />
          </div>
          <p className="eyebrow text-[#d7b878]">Meet your physician</p>
          <h3 className="font-display text-[36px] md:text-[44px] mt-2">
            Dr. Gail Ravello
          </h3>
          <p className="text-[#d7b878] mt-1 tracking-widest text-xs uppercase">
            IMD · ND · PhD · MH · CNC
          </p>
          <p className="mt-5 text-[15px] leading-relaxed max-w-2xl text-[#e8e1c9]">
            Dr. Ravello is board-certified by the American Naturopathic Medical Certification Board with over 29 years of experience in private practice and hospital outpatient care. She currently welcomes new patients in Roswell, Alpharetta and Atlanta.
          </p>
          <div className="mt-7">
            <Link to="/request-appointment">
              <Button className="btn-lift h-11 px-6 rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22] font-medium">
                Schedule a Consultation
                <ArrowRight size={16} className="ml-2" />
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* TESTIMONIALS */}
      <section className="max-w-6xl mx-auto px-6 mt-24">
        <div className="text-center">
          <p className="eyebrow text-[#8a6a3c]">Our clients</p>
          <h2 className="font-display text-[36px] md:text-[44px] text-[#1f2a22] mt-2">See What They Say</h2>
        </div>
        <div className="grid md:grid-cols-2 gap-6 mt-10">
          {testimonials.map((t, i) => (
            <div key={i} className="card-hover rounded-2xl bg-[#fbf7ee] border border-[#e7dfc9] p-7">
              <div className="font-display text-[36px] leading-none text-[#c19a4b]">“</div>
              <p className="text-[#3a3a3a] leading-relaxed -mt-2">{t.quote}</p>
              <div className="mt-5 text-xs tracking-[0.25em] uppercase text-[#8a6a3c]">— {t.author}</div>
            </div>
          ))}
        </div>
      </section>

      {/* VIP SIGNUP */}
      <section className="max-w-3xl mx-auto px-6 mt-24">
        <div className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center">
          <h3 className="font-display text-[30px] md:text-[36px] text-[#1f2a22]">Join our VIP list</h3>
          <p className="text-[#5a5a5a] mt-2">
            Get <span className="text-[#2f4a3a] font-medium">$20 off</span> your first visit plus early access to new protocols &amp; wellness events.
          </p>
          <form onSubmit={handleVIPJoin} className="mt-6 flex flex-col sm:flex-row gap-3 max-w-md mx-auto">
            <Input
              type="email"
              placeholder="your@email.com"
              value={vipEmail}
              onChange={(e) => setVipEmail(e.target.value)}
              className="h-12 rounded-full bg-[#f6f1e6] border-[#e0d6bc] px-5 text-[14px]"
            />
            <Button
              type="submit"
              className="btn-lift h-12 px-7 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
            >
              Join
            </Button>
          </form>
        </div>
      </section>

      {/* VISIT / PATIENT PORTAL */}
      <section className="max-w-6xl mx-auto px-6 mt-24 grid md:grid-cols-2 gap-6">
        <div className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-8">
          <p className="eyebrow text-[#8a6a3c]">Patient Portal</p>
          <h3 className="font-display text-[30px] text-[#1f2a22] mt-2">Manage your care from home</h3>
          <p className="text-[#5a5a5a] text-sm mt-3">
            Securely view labs, update intake forms, and message your care team.
          </p>
          <div className="mt-6 flex flex-col sm:flex-row gap-3">
            <Link to="/login">
              <Button className="btn-lift h-11 px-6 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
                Patient Sign In
              </Button>
            </Link>
          </div>
        </div>

        <div className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-8">
          <p className="eyebrow text-[#8a6a3c]">Our Location</p>
          <h3 className="font-display text-[24px] text-[#1f2a22] mt-2">Roswell, Georgia</h3>
          <div className="mt-4 text-[14px] text-[#3a3a3a] space-y-2">
            <div className="flex items-start gap-2"><MapPin size={16} className="mt-0.5 text-[#2f4a3a]" /><span>{brand.address}</span></div>
            <div className="flex items-center gap-2"><Phone size={16} className="text-[#2f4a3a]" /><a href={`tel:${brand.phone.replace(/[^0-9]/g, "")}`} className="hover:text-[#2f4a3a]">{brand.phone}</a></div>
            <div className="flex items-start gap-2"><Clock size={16} className="mt-0.5 text-[#2f4a3a]" />
              <ul className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px]">
                {hours.map((h) => (
                  <li key={h.day} className="flex justify-between gap-3">
                    <span className="text-[#6a6a6a]">{h.day}</span><span>{h.time}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* STAFF SIGN-IN */}
      <section className="max-w-6xl mx-auto px-6 mt-20">
        <div className="border-t border-[#e7dfc9] pt-10 flex flex-col md:flex-row items-center justify-between gap-5">
          <div className="text-center md:text-left">
            <div className="eyebrow text-[#8a6a3c]">Staff</div>
            <div className="font-display text-[22px] text-[#1f2a22] mt-1">Team Portal</div>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => toast({ title: "Google SSO coming soon", description: "Use email sign-in with your admin credentials." })}
              className="inline-flex items-center gap-2 text-sm text-[#3a3a3a] hover:text-[#2f4a3a]"
            >
              <svg width="16" height="16" viewBox="0 0 48 48">
                <path fill="#FFC107" d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12s5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24s8.955,20,20,20s20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"/>
                <path fill="#FF3D00" d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"/>
                <path fill="#4CAF50" d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"/>
                <path fill="#1976D2" d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"/>
              </svg>
              Sign in with Google
            </button>
            <span className="text-[#c19a4b]">·</span>
            <Link to="/login" className="text-sm text-[#2f4a3a] hover:underline">
              Email Sign In
            </Link>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
