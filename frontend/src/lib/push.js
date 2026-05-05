import api from "./api";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
  return out;
}

/** Best-effort: register the SW (already registered in prod via index.js),
 *  fetch the VAPID public key, request notification permission, subscribe,
 *  and POST the subscription to /api/push/subscribe.
 *  Silent failure — never blocks UI. */
export async function ensurePushSubscription() {
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return false;
    const reg = (await navigator.serviceWorker.getRegistration()) || (await navigator.serviceWorker.ready);
    if (!reg) return false;

    if (Notification.permission === "denied") return false;
    if (Notification.permission !== "granted") {
      const p = await Notification.requestPermission();
      if (p !== "granted") return false;
    }

    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      const r = await api.get("/push/public-key");
      const key = r.data?.public_key;
      if (!key) return false;
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
    }
    const body = JSON.parse(JSON.stringify(sub));
    await api.post("/push/subscribe", { subscription: body });
    return true;
  } catch (e) {
    console.warn("ensurePushSubscription:", e);
    return false;
  }
}
