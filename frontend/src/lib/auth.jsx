import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import api, { LS, touchActivity, isIdle, IDLE_TIMEOUT_MS } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(LS.user) || "null");
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {}
    localStorage.removeItem(LS.access);
    localStorage.removeItem(LS.refresh);
    localStorage.removeItem(LS.user);
    localStorage.removeItem(LS.lastActivity);
    setUser(null);
  }, []);

  const refreshMe = useCallback(async () => {
    if (!localStorage.getItem(LS.access)) {
      setLoading(false);
      return;
    }
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
      localStorage.setItem(LS.user, JSON.stringify(data));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshMe();
  }, [refreshMe]);

  // Idle session timeout
  useEffect(() => {
    if (!user) return;
    touchActivity();
    const onActivity = () => touchActivity();
    const events = ["click", "mousemove", "keydown", "scroll"];
    events.forEach((e) => window.addEventListener(e, onActivity));
    const t = setInterval(() => {
      if (isIdle()) {
        logout();
      }
    }, 30_000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, onActivity));
      clearInterval(t);
    };
  }, [user, logout]);

  async function loginWithPassword(email, password, mfaToken) {
    const { data } = await api.post("/auth/login", {
      email,
      password,
      mfa_token: mfaToken,
    });
    if (data.mfa_required) {
      return { mfa_required: true };
    }
    localStorage.setItem(LS.access, data.access_token);
    localStorage.setItem(LS.refresh, data.refresh_token);
    localStorage.setItem(LS.user, JSON.stringify(data.user));
    touchActivity();
    setUser(data.user);
    return { user: data.user };
  }

  async function registerNew(payload) {
    const { data } = await api.post("/auth/register", payload);
    localStorage.setItem(LS.access, data.access_token);
    localStorage.setItem(LS.refresh, data.refresh_token);
    localStorage.setItem(LS.user, JSON.stringify(data.user));
    touchActivity();
    setUser(data.user);
    return { user: data.user };
  }

  async function loginWithGoogleSession(sessionId) {
    const { data } = await api.post("/auth/google/session", null, {
      headers: { "X-Session-ID": sessionId },
    });
    localStorage.setItem(LS.access, data.access_token);
    localStorage.setItem(LS.refresh, data.refresh_token);
    localStorage.setItem(LS.user, JSON.stringify(data.user));
    touchActivity();
    setUser(data.user);
    return { user: data.user };
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, logout, loginWithPassword, registerNew, refreshMe, setUser, loginWithGoogleSession }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}

export function roleHome(role) {
  if (role === "admin") return "/portal/admin";
  if (role === "practitioner") return "/portal/provider";
  if (role === "staff") return "/portal/staff";
  if (role === "auditor") return "/portal/admin/audit";
  return "/portal/patient";
}
