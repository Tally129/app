import React from "react";
import { useAuth } from "../lib/auth";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "./ui/dialog";
import { Button } from "./ui/button";
import { ShieldAlert } from "lucide-react";

const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 min
const WARNING_MS = 2 * 60 * 1000;       // warn 2 min before

/**
 * HIPAA §164.312(a)(2)(iii) — automatic logoff.
 * Signs the user out after 15 minutes of inactivity, with a 2-minute warning
 * modal that lets them "Stay signed in".
 */
export default function SessionTimeout() {
  const { user, logout } = useAuth();
  const [warn, setWarn] = React.useState(false);
  const [countdown, setCountdown] = React.useState(WARNING_MS / 1000);
  const lastActivity = React.useRef(Date.now());
  const warnTimerRef = React.useRef(null);
  const logoutTimerRef = React.useRef(null);
  const tickRef = React.useRef(null);

  const arm = React.useCallback(() => {
    if (warnTimerRef.current) clearTimeout(warnTimerRef.current);
    if (logoutTimerRef.current) clearTimeout(logoutTimerRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
    warnTimerRef.current = setTimeout(() => {
      setCountdown(WARNING_MS / 1000);
      setWarn(true);
      tickRef.current = setInterval(() => setCountdown((v) => Math.max(0, v - 1)), 1000);
    }, IDLE_TIMEOUT_MS - WARNING_MS);
    logoutTimerRef.current = setTimeout(() => {
      setWarn(false);
      try { logout(); } catch { /* ignore — already signed out */ }
      window.location.href = "/login?reason=inactivity";
    }, IDLE_TIMEOUT_MS);
  }, [logout]);

  const bump = React.useCallback(() => {
    if (Date.now() - lastActivity.current < 5000 && !warn) return; // debounce
    lastActivity.current = Date.now();
    if (warn) return; // don't silently reset while the modal is showing
    arm();
  }, [arm, warn]);

  React.useEffect(() => {
    if (!user) return;
    arm();
    const events = ["mousemove", "keydown", "click", "scroll", "touchstart"];
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }));
    return () => {
      events.forEach((e) => window.removeEventListener(e, bump));
      if (warnTimerRef.current) clearTimeout(warnTimerRef.current);
      if (logoutTimerRef.current) clearTimeout(logoutTimerRef.current);
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, [user, arm, bump]);

  const stay = () => {
    setWarn(false);
    lastActivity.current = Date.now();
    arm();
  };

  if (!user) return null;

  const mm = Math.floor(countdown / 60).toString().padStart(2, "0");
  const ss = (countdown % 60).toString().padStart(2, "0");

  return (
    <Dialog open={warn} onOpenChange={() => {}}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-sm" data-testid="session-timeout-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl flex items-center gap-2">
            <ShieldAlert size={20} className="text-[#7a2a2a]" /> Session about to expire
          </DialogTitle>
          <DialogDescription>
            For HIPAA compliance we sign you out after 15 minutes of inactivity.
            Signing out in <strong data-testid="session-countdown">{mm}:{ss}</strong>.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => { try { logout(); } catch { /* ignore */ } window.location.href = "/login"; }} data-testid="session-sign-out">
            Sign out now
          </Button>
          <Button onClick={stay} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="session-stay-signed-in">
            Stay signed in
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
