import React from "react";
import { Bell, BellOff, X, Loader2 } from "lucide-react";
import { useAuth } from "../lib/auth";
import { ensurePushSubscription } from "../lib/push";
import { useToast } from "../hooks/use-toast";

const DISMISS_KEY = "nms_push_optin_dismissed_v1";

/**
 * Lightweight in-app banner that asks the signed-in user to enable browser
 * push notifications. Shown only once per device unless the user explicitly
 * accepts (in which case we mark `granted`) or dismisses.
 *
 * Logic:
 *  • Hidden if Notification API isn't available (e.g. iOS Safari w/out PWA).
 *  • Hidden if the user has already granted, denied, or dismissed locally.
 *  • Hidden if no signed-in user.
 */
export default function PushOptInBanner() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [show, setShow] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!user) return setShow(false);
    if (typeof window === "undefined") return;
    if (!("Notification" in window) || !("serviceWorker" in navigator)) return;
    let dismissed = "";
    try { dismissed = localStorage.getItem(DISMISS_KEY) || ""; } catch {}
    if (dismissed) return;
    if (Notification.permission === "granted" || Notification.permission === "denied") return;
    // Slight delay so we don't pop right at first paint
    const t = setTimeout(() => setShow(true), 1200);
    return () => clearTimeout(t);
  }, [user]);

  if (!show) return null;

  const enable = async () => {
    setBusy(true);
    try {
      const ok = await ensurePushSubscription();
      if (ok) {
        toast({ title: "Notifications enabled", description: "We'll ping you for visits, forms, and protocol updates." });
        try { localStorage.setItem(DISMISS_KEY, "granted"); } catch {}
        setShow(false);
      } else {
        toast({ title: "Could not enable notifications", description: "Browser permission was denied or unavailable." });
        try { localStorage.setItem(DISMISS_KEY, "denied"); } catch {}
        setShow(false);
      }
    } finally { setBusy(false); }
  };

  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, "dismissed"); } catch {}
    setShow(false);
  };

  return (
    <div
      className="fixed bottom-4 right-4 left-4 sm:left-auto sm:max-w-sm z-40 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] shadow-lg p-4 flex items-start gap-3"
      role="dialog"
      aria-live="polite"
      data-testid="push-optin-banner"
    >
      <div className="rounded-full bg-[#f1ead8] p-2 text-[#8a6a3c] flex-shrink-0"><Bell size={18} /></div>
      <div className="flex-1 min-w-0">
        <div className="font-display text-base text-[#1f2a22] leading-tight">Stay in the loop</div>
        <p className="text-xs text-[#5a5a5a] mt-1">
          Enable browser notifications for visit reminders, new forms, and protocol updates. We never push marketing.
        </p>
        <div className="flex items-center gap-2 mt-3">
          <button
            onClick={enable}
            disabled={busy}
            className="rounded-full px-4 h-8 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] text-xs uppercase tracking-widest inline-flex items-center disabled:opacity-60"
            data-testid="push-optin-enable"
          >
            {busy ? <Loader2 size={11} className="animate-spin mr-1" /> : null}
            {busy ? "Enabling…" : "Enable"}
          </button>
          <button
            onClick={dismiss}
            className="text-xs text-[#6a6a6a] hover:text-[#3a3a3a] inline-flex items-center gap-1"
            data-testid="push-optin-dismiss"
          >
            <BellOff size={11} /> Not now
          </button>
        </div>
      </div>
      <button onClick={dismiss} className="text-[#8a6a3c] hover:text-[#3a3a3a]" aria-label="Close" data-testid="push-optin-close">
        <X size={16} />
      </button>
    </div>
  );
}
