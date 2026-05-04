import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Checkbox } from "../../components/ui/checkbox";
import { Switch } from "../../components/ui/switch";
import { useToast } from "../../hooks/use-toast";
import { Bell, Mail, Smartphone } from "lucide-react";

export default function AdminReminders() {
  const { toast } = useToast();
  const [settings, setSettings] = React.useState({
    appointment_reminder_hours_before: 24,
    appointment_reminder_channels: ["email"],
    follow_up_days_after: 7,
    enabled: true,
  });
  const [busy, setBusy] = React.useState(false);
  const [runResult, setRunResult] = React.useState(null);

  React.useEffect(() => {
    api.get("/reminders/settings").then((r) => setSettings(r.data));
  }, []);

  const toggleChannel = (ch) => {
    const on = settings.appointment_reminder_channels.includes(ch);
    setSettings({
      ...settings,
      appointment_reminder_channels: on
        ? settings.appointment_reminder_channels.filter((x) => x !== ch)
        : [...settings.appointment_reminder_channels, ch],
    });
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.put("/reminders/settings", settings);
      toast({ title: "Settings saved" });
    } catch { toast({ title: "Failed" }); } finally { setBusy(false); }
  };

  const runNow = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/reminders/run");
      setRunResult(data);
      toast({ title: "Scheduler ran", description: `${data.processed} reminders processed (stubbed).` });
    } catch { toast({ title: "Failed" }); } finally { setBusy(false); }
  };

  return (
    <PortalLayout>
      <PortalHeader title="Reminders" subtitle="Appointment notification settings (SendGrid / Twilio wiring is stubbed until keys are provided)." />

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 max-w-2xl space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Bell className="text-[#2f4a3a]" />
            <div>
              <div className="font-medium">Reminders enabled</div>
              <div className="text-xs text-[#6a6a6a]">Master switch for all outbound reminders</div>
            </div>
          </div>
          <Switch checked={settings.enabled} onCheckedChange={(v) => setSettings({ ...settings, enabled: !!v })} />
        </div>

        <div>
          <Label>Send reminder (hours before appointment)</Label>
          <Input
            type="number"
            min={1}
            max={168}
            value={settings.appointment_reminder_hours_before}
            onChange={(e) => setSettings({ ...settings, appointment_reminder_hours_before: Number(e.target.value) || 24 })}
            className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] max-w-xs"
          />
        </div>

        <div>
          <Label>Channels</Label>
          <div className="mt-2 flex flex-wrap gap-3">
            <label className="inline-flex items-center gap-2 rounded-full border border-[#e0d6bc] bg-[#f6f1e6] px-3 py-2 cursor-pointer text-sm">
              <Checkbox checked={settings.appointment_reminder_channels.includes("email")} onCheckedChange={() => toggleChannel("email")} />
              <Mail size={14} /> Email (SendGrid)
            </label>
            <label className="inline-flex items-center gap-2 rounded-full border border-[#e0d6bc] bg-[#f6f1e6] px-3 py-2 cursor-pointer text-sm">
              <Checkbox checked={settings.appointment_reminder_channels.includes("sms")} onCheckedChange={() => toggleChannel("sms")} />
              <Smartphone size={14} /> SMS (Twilio)
            </label>
          </div>
          <p className="text-xs text-[#6a6a6a] mt-2">Messages never include PHI — just a generic reminder.</p>
        </div>

        <div>
          <Label>Follow-up nudge (days after visit)</Label>
          <Input
            type="number"
            min={1}
            max={90}
            value={settings.follow_up_days_after}
            onChange={(e) => setSettings({ ...settings, follow_up_days_after: Number(e.target.value) || 7 })}
            className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] max-w-xs"
          />
        </div>

        <div className="flex gap-3">
          <Button onClick={save} disabled={busy} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">Save settings</Button>
          <Button onClick={runNow} disabled={busy} variant="outline" className="rounded-full border-[#c19a4b] text-[#8a6a3c] bg-transparent hover:bg-[#c19a4b] hover:text-[#1f2a22]">Run scheduler now</Button>
        </div>

        {runResult && (
          <div className="text-xs text-[#6a6a6a] border-t border-[#e7dfc9] pt-3">
            Last run processed <b>{runResult.processed}</b> reminder{runResult.processed === 1 ? "" : "s"} (logged to integration_log as _stubbed).
          </div>
        )}
      </div>
    </PortalLayout>
  );
}
