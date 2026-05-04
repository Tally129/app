import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

export const LS = {
  access: "nms_access",
  refresh: "nms_refresh",
  user: "nms_user",
  lastActivity: "nms_last_activity",
};

export const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 min

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(LS.access);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing = null;
async function doRefresh() {
  if (refreshing) return refreshing;
  const refresh = localStorage.getItem(LS.refresh);
  if (!refresh) throw new Error("No refresh token");
  refreshing = axios
    .post(`${API_BASE}/auth/refresh`, { refresh_token: refresh })
    .then((r) => {
      localStorage.setItem(LS.access, r.data.access_token);
      localStorage.setItem(LS.refresh, r.data.refresh_token);
      localStorage.setItem(LS.user, JSON.stringify(r.data.user));
      return r.data.access_token;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error?.response?.status === 401 && !original._retry && !original.url.includes("/auth/")) {
      original._retry = true;
      try {
        const newToken = await doRefresh();
        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      } catch (e) {
        localStorage.removeItem(LS.access);
        localStorage.removeItem(LS.refresh);
        localStorage.removeItem(LS.user);
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default api;

export function touchActivity() {
  localStorage.setItem(LS.lastActivity, String(Date.now()));
}

export function isIdle() {
  const last = Number(localStorage.getItem(LS.lastActivity) || 0);
  return last && Date.now() - last > IDLE_TIMEOUT_MS;
}
