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
          <Link to="/signup">
            <Button
              variant="outline"
              className="btn-lift h-12 px-8 rounded-full border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#2f4a3a] hover:text-[#f6f1e6] text-[15px] bg-transparent"
            >
              Create a Client Account
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

      {/* MEMBERSHIP TIERS */}
      <section id="membership" className="max-w-6xl mx-auto px-6 mt-10">
        <div className="text-center">
          <p className="eyebrow text-[#8a6a3c]">Join as a member</p>
          <h2 className="font-display text-[40px] md:text-[52px] text-[#1f2a22] mt-2">Membership Tiers</h2>
          <p className="text-[#5a5a5a] mt-3">Monthly value, physician-led care. Cancel anytime.</p>
          <div className="mt-4 flex items-center justify-center gap-3">
            <span className="leaf-divider" /><Leaf size={14} className="text-[#c19a4b]" /><span className="leaf-divider" />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-10">
          {membershipTiers.map((t) => (
            <div
              key={t.id}
              className={`card-hover relative rounded-2xl border bg-[#fbf7ee] p-7 flex flex-col ${
                t.featured ? "border-[#c19a4b] tier-featured" : "border-[#e7dfc9]"
              }`}
            >
              {t.featured && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#c19a4b] text-[#1f2a22] text-[11px] tracking-widest uppercase px-3 py-1 rounded-full">
                  Most Popular
                </div>
              )}
              <h3 className="font-display text-[26px] text-[#1f2a22]">{t.name}</h3>
              <div className="mt-2 flex items-baseline gap-1">
                <span className="font-display text-[36px] text-[#2f4a3a]">${t.price}</span>
                <span className="text-[#7a7a7a] text-sm">{t.cadence}</span>
              </div>
              <p className="text-[#5a5a5a] text-sm mt-3 leading-relaxed">{t.blurb}</p>
              <ul className="mt-5 space-y-2.5">
                {t.perks.map((p) => (
                  <li key={p} className="flex items-start gap-2 text-[14px] text-[#3a3a3a]">
                    <Check size={16} className="mt-0.5 text-[#2f4a3a] shrink-0" />
                    <span>{p}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-auto pt-6">
                <Link to="/signup">
                  <Button
                    className={`btn-lift w-full h-11 rounded-full ${
                      t.featured
                        ? "bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                        : "bg-[#fbf7ee] border border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#2f4a3a] hover:text-[#f6f1e6]"
                    }`}
                  >
                    Join Now
                  </Button>
                </Link>
              </div>
            </div>
          ))}
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
            <Link to="/signup">
              <Button variant="outline" className="btn-lift h-11 px-6 rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6]">
                Create Account
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

      <Footer />
    </div>
  );
}
