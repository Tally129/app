/* Natural Medical Solutions — service worker
 * Network-first for /api (fresh PHI), cache-first for static assets.
 */
const VERSION = "nms-v1";
const STATIC_CACHE = `${VERSION}-static`;
const ASSET_PATTERNS = [/\.css$/, /\.js$/, /\.woff2?$/, /\.png$/, /\.svg$/, /\.ico$/];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((c) => c.addAll(["/", "/manifest.json"]).catch(() => null))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Never cache API or auth — protect PHI
  if (url.pathname.startsWith("/api/") || url.pathname.includes("/auth/")) {
    return;
  }

  const isStatic = ASSET_PATTERNS.some((p) => p.test(url.pathname));
  if (isStatic) {
    event.respondWith(
      caches.match(req).then((hit) =>
        hit ||
        fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(STATIC_CACHE).then((c) => c.put(req, copy));
          return res;
        }).catch(() => caches.match("/"))
      )
    );
    return;
  }

  // Navigation: network-first, fall back to cached shell
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match("/"))
    );
  }
});
