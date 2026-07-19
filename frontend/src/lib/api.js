import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

// Sprint 2: NO refresh token in browser storage. Access token stays in memory only.
// LS.user + LS.lastActivity are UX conveniences that do NOT grant PHI access.
export const LS = {
  user: "nms_user",
  lastActivity: "nms_last_activity",
};

export const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 min
export function touchActivity() { try { localStorage.setItem(LS.lastActivity, String(Date.now())); } catch {} }
export function isIdle() {
  try {
    const v = parseInt(localStorage.getItem(LS.lastActivity) || "0", 10);
    return v > 0 && (Date.now() - v) > IDLE_TIMEOUT_MS;
  } catch { return false; }
}

// In-memory access token — never written to any storage.
let _access_token = null;
export function setAccessToken(t) { _access_token = t || null; }
export function getAccessToken() { return _access_token; }
export function clearAccessToken() { _access_token = null; }

// Cross-tab logout + refresh coordination.
// The `nms_auth` BroadcastChannel carries EVENT NAMES ONLY — never token
// values. The `nms_refresh` Web Lock (when available) serializes refresh
// calls across tabs so only one tab talks to /auth/refresh at a time; the
// others wait for it to finish and then perform their own refresh (which
// hits the concurrency-grace path with a fresh cookie).
let bc = null;
try { bc = new BroadcastChannel("nms_auth"); } catch { bc = null; }
const bcListeners = new Set();
if (bc) {
  bc.addEventListener("message", (ev) => {
    bcListeners.forEach((cb) => { try { cb(ev.data); } catch {} });
  });
}
export function onAuthBroadcast(cb) { bcListeners.add(cb); return () => bcListeners.delete(cb); }
export function broadcastAuth(event) { try { bc && bc.postMessage({ event, ts: Date.now() }); } catch {} }

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = _access_token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  // /auth/refresh MUST send + receive the HttpOnly cookie
  if (config.url && config.url.includes("/auth/refresh")) {
    config.withCredentials = true;
  }
  return config;
});

// Single-flight refresh queue + cross-tab exclusive lock.
let refreshing = null;

async function _refreshOnce() {
  // Perform the actual network call. Handles the backend's 409
  // `concurrency_retry` by immediately retrying with the fresh cookie
  // that the winning tab installed. Two retries max, then bail.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await axios.post(`${API_BASE}/auth/refresh`, {}, { withCredentials: true });
      _access_token = r.data.access_token;
      if (r.data.user) localStorage.setItem(LS.user, JSON.stringify(r.data.user));
      // Notify any idle tabs — event only, never the token.
      broadcastAuth("refresh-done");
      return _access_token;
    } catch (e) {
      if (e?.response?.status === 409 && attempt === 0) {
        // 409 = server observed a same-family used token within the grace
        // window. Another tab rotated ahead of us. Wait a beat so the
        // browser applies the winning tab's Set-Cookie, then retry.
        await new Promise((res) => setTimeout(res, 120));
        continue;
      }
      throw e;
    }
  }
  throw new Error("refresh_retry_exhausted");
}

async function doRefresh() {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    // Web Locks API serialises refresh across ALL tabs in this origin —
    // solves the multi-tab race that otherwise triggers concurrency 409s
    // for tabs 2..N. When Locks are unavailable, fall back to the
    // per-tab single-flight (`refreshing`).
    if (typeof navigator !== "undefined" && navigator.locks && typeof navigator.locks.request === "function") {
      return await navigator.locks.request(
        "nms_refresh_lock",
        { mode: "exclusive" },
        async () => _refreshOnce(),
      );
    }
    return await _refreshOnce();
  })().finally(() => { refreshing = null; });
  return refreshing;
}
export { doRefresh };

// Retry cap protects against infinite 401 loops.
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    const status = error?.response?.status;
    if (status === 401 && original && !original._retry && !(original.url || "").includes("/auth/")) {
      original._retry = true;
      try {
        const newToken = await doRefresh();
        if (newToken) original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      } catch (e) {
        // Only escalate to logout when the refresh really failed
        // (session revoked / cookie missing) — never on the concurrency
        // retry path (that's swallowed inside _refreshOnce).
        _access_token = null;
        localStorage.removeItem(LS.user);
        broadcastAuth("session-expired");
        if (!window.location.pathname.startsWith("/login")) {
          window.location.href = "/login";
        }
      }
    }
    // Tag every 403 as an EXPECTED authorization denial. Callers who care
    // handle it explicitly; anyone who forgets to `.catch` won't produce a
    // scary red console error. The `handled` flag is consumed by our global
    // unhandledrejection listener below.
    if (status === 403) {
      try {
        error.isAuthDenied = true;
        error.handled = true;
      } catch { /* frozen error object */ }
    }
    return Promise.reject(error);
  }
);

// Global safety net for background fetches that forget to `.catch`.
// Purpose: prevent expected 403 (and stale-request 401 already redirected)
// from surfacing as red "Uncaught (in promise) AxiosError" console noise or
// triggering React error boundaries. We DO NOT swallow other errors — real
// bugs still propagate.
if (typeof window !== "undefined" && !window.__nms_rejection_installed) {
  window.__nms_rejection_installed = true;
  window.addEventListener("unhandledrejection", (ev) => {
    const err = ev.reason;
    const status = err?.response?.status;
    if (status === 403 || err?.isAuthDenied) {
      // Log at debug level (visible only if devtools filter allows) and
      // suppress the default surfacing.
      console.debug("[nms] suppressed 403 auth denial:", err?.config?.url || err);
      ev.preventDefault();
    }
  });
}

export { api };
export default api;
