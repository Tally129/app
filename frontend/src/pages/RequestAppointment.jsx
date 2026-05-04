import React from "react";
import { Link, useNavigate } from "react-router-dom";
import Logo from "../components/Logo";
import Footer from "../components/Footer";
import { services, addOns, LS_KEYS } from "../mock";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Calendar } from "../components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { Sparkles, ArrowLeft, Check, CalendarIcon } from "lucide-react";
import { useToast } from "../hooks/use-toast";
import { format } from "date-fns";

export default function RequestAppointment() {
  const { toast } = useToast();
  const navigate = useNavigate();

  const [form, setForm] = React.useState({
    fullName: "",
    email: "",
    phone: "",
    returning: "first",
    service: "",
    date: null,
    time: "",
    notes: ""
  });
  const [selectedAddOns, setSelectedAddOns] = React.useState([]);
  const [submitting, setSubmitting] = React.useState(false);

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const toggleAddOn = (id) => {
    setSelectedAddOns((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.fullName) {
      toast({ title: "Full name is required" });
      return;
    }
    setSubmitting(true);
    const record = { ...form, addOns: selectedAddOns, ts: Date.now() };
    const existing = JSON.parse(localStorage.getItem(LS_KEYS.appointments) || "[]");
    localStorage.setItem(LS_KEYS.appointments, JSON.stringify([...existing, record]));
    try {
      await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/public/appointment-request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fullName: form.fullName,
          email: form.email,
          phone: form.phone,
          returning: form.returning,
          service: form.service,
          date: form.date ? form.date.toISOString() : null,
          time: form.time,
          notes: form.notes,
          addOns: selectedAddOns,
        }),
      });
    } catch {}
    setTimeout(() => {
      setSubmitting(false);
      toast({
        title: "Request received",
        description: "A care team member will personally confirm your appointment within 24 hours.",
      });
      navigate("/");
    }, 400);
  };

  const timeSlots = ["9:00 AM", "10:30 AM", "12:00 PM", "2:00 PM", "3:30 PM", "5:00 PM"];

  return (
    <div className="page-fade min-h-screen bg-parchment font-body">
      <div className="top-ribbon" />

      <div className="max-w-3xl mx-auto px-6 pt-10 pb-6">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-[#6a6a6a] hover:text-[#2f4a3a]">
          <ArrowLeft size={16} /> Back to home
        </Link>
      </div>

      <section className="max-w-3xl mx-auto px-6 text-center">
        <div className="flex justify-center"><Logo size={92} /></div>
        <h1 className="font-display text-[44px] md:text-[54px] text-[#1f2a22] mt-8">Request an Appointment</h1>
        <p className="text-[#5a5a5a] mt-3 max-w-xl mx-auto leading-relaxed">
          Each appointment is hand-curated by our team. Share a few details and we’ll personally confirm your perfect time slot.
        </p>
      </section>

      <section className="max-w-3xl mx-auto px-6 mt-10">
        <form onSubmit={handleSubmit} className="rounded-3xl border border-[#e7dfc9] bg-[#fbf7ee] p-7 md:p-10 space-y-6">
          <div className="grid md:grid-cols-2 gap-5">
            <div>
              <Label htmlFor="fullName" className="text-[#3a3a3a]">Full Name *</Label>
              <Input
                id="fullName"
                value={form.fullName}
                onChange={(e) => set("fullName", e.target.value)}
                className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg"
                placeholder="Jane Doe"
                required
              />
            </div>
            <div>
              <Label htmlFor="email" className="text-[#3a3a3a]">Email</Label>
              <Input
                id="email"
                type="email"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg"
                placeholder="jane@example.com"
              />
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-5">
            <div>
              <Label htmlFor="phone" className="text-[#3a3a3a]">Phone</Label>
              <Input
                id="phone"
                value={form.phone}
                onChange={(e) => set("phone", e.target.value)}
                className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg"
                placeholder="(770) 555-0100"
              />
            </div>
            <div>
              <Label className="text-[#3a3a3a]">Returning Patient?</Label>
              <Select value={form.returning} onValueChange={(v) => set("returning", v)}>
                <SelectTrigger className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="first">First Time</SelectItem>
                  <SelectItem value="returning">Returning Patient</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <Label className="text-[#3a3a3a]">Service of Interest</Label>
            <Select value={form.service} onValueChange={(v) => set("service", v)}>
              <SelectTrigger className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg">
                <SelectValue placeholder="Select a service or leave blank for consultation" />
              </SelectTrigger>
              <SelectContent>
                {services.map((s) => (
                  <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Add-Ons */}
          <div className="rounded-2xl border border-[#e0d6bc] bg-[#f6f1e6] p-5">
            <div className="flex items-center gap-2 text-[#8a6a3c]">
              <Sparkles size={16} />
              <span className="eyebrow">Enhance Your Visit</span>
            </div>
            <p className="text-sm text-[#5a5a5a] mt-1.5">Tap to add. Pairs beautifully with any consultation.</p>
            <div className="grid sm:grid-cols-2 gap-3 mt-4">
              {addOns.map((a) => {
                const active = selectedAddOns.includes(a.id);
                return (
                  <button
                    type="button"
                    key={a.id}
                    onClick={() => toggleAddOn(a.id)}
                    className={`btn-lift flex items-center justify-between rounded-full px-5 py-2.5 text-sm border transition ${
                      active
                        ? "bg-[#2f4a3a] text-[#f6f1e6] border-[#2f4a3a]"
                        : "bg-[#fbf7ee] text-[#3a3a3a] border-[#e0d6bc] hover:border-[#c19a4b]"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      {active && <Check size={14} />}
                      {a.name}
                    </span>
                    <span className={active ? "text-[#d7b878]" : "text-[#8a6a3c]"}>+${a.price}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-5">
            <div>
              <Label className="text-[#3a3a3a]">Preferred Date</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    className="mt-2 w-full h-11 justify-start rounded-lg bg-[#f6f1e6] border-[#e0d6bc] text-[#3a3a3a] font-normal hover:bg-[#f1ead8]"
                  >
                    <CalendarIcon size={16} className="mr-2 text-[#2f4a3a]" />
                    {form.date ? format(form.date, "EEEE, MMM d, yyyy") : "Choose a date"}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="p-0 bg-[#fbf7ee] border-[#e0d6bc]" align="start">
                  <Calendar
                    mode="single"
                    selected={form.date}
                    onSelect={(d) => set("date", d)}
                    disabled={(d) => d < new Date(new Date().setHours(0,0,0,0))}
                    initialFocus
                  />
                </PopoverContent>
              </Popover>
            </div>
            <div>
              <Label className="text-[#3a3a3a]">Preferred Time</Label>
              <Select value={form.time} onValueChange={(v) => set("time", v)}>
                <SelectTrigger className="mt-2 h-11 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg">
                  <SelectValue placeholder="Select a time" />
                </SelectTrigger>
                <SelectContent>
                  {timeSlots.map((t) => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <Label htmlFor="notes" className="text-[#3a3a3a]">Anything we should know?</Label>
            <Textarea
              id="notes"
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] rounded-lg min-h-[90px]"
              placeholder="Share any concerns, conditions, or goals so we can tailor your visit."
            />
          </div>

          <div className="pt-2">
            <Button
              type="submit"
              disabled={submitting}
              className="btn-lift h-12 w-full rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] text-[15px]"
            >
              {submitting ? "Submitting…" : "Submit Appointment Request"}
            </Button>
            <p className="text-center text-xs text-[#8a8a8a] mt-3">
              We’ll personally confirm within 24 hours. No payment required to request.
            </p>
          </div>
        </form>
      </section>

      <Footer />
    </div>
  );
}
