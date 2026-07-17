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

// Cross-tab logout coordination — no token values are broadcast, only the signal.
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

// Single-flight refresh queue.
let refreshing = null;
async function doRefresh() {
  if (refreshing) return refreshing;
  refreshing = axios
    .post(`${API_BASE}/auth/refresh`, {}, { withCredentials: true })
    .then((r) => {
      _access_token = r.data.access_token;
      if (r.data.user) localStorage.setItem(LS.user, JSON.stringify(r.data.user));
      return _access_token;
    })
    .catch((e) => {
      // 409 concurrency_retry → retry ONCE using the cookie the winner already set.
      if (e?.response?.status === 409) {
        return axios.post(`${API_BASE}/auth/refresh`, {}, { withCredentials: true })
          .then((r2) => { _access_token = r2.data.access_token; return _access_token; });
      }
      throw e;
    })
    .finally(() => { refreshing = null; });
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
        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      } catch {
        _access_token = null;
        localStorage.removeItem(LS.user);
        broadcastAuth("logout");
        if (!window.location.pathname.startsWith("/login")) {
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);

export default api;
