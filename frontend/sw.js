// GoldScalper service worker — shell caching, network-first for fast live updates.

const VERSION = "gs-v15";
const SHELL = [
  "/",
  "/index.html?v=20261015_01",
  "/manifest.json",
  "/css/cockpit.css?v=20261015_01",
  "/css/agents.css?v=20261015_01",
  "/js/vendor/lightweight-charts.standalone.production.js?v=20261015_01",
  "/js/app.js?v=20261015_01",
  "/js/ws.js?v=20261015_01",
  "/js/chart.js?v=20261015_01",
  "/js/components.js?v=20261015_01",
  "/js/agents.js?v=20261015_01",
  "/icons/icon.svg",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => undefined)
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // live endpoints are never cached
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put("/index.html", copy));
          return res;
        })
        .catch(() => caches.match("/index.html")),
    );
    return;
  }

  event.respondWith(
    fetch(request)
      .then((res) => {
        if (res && res.status === 200 && res.type === "basic") {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(request, copy));
        }
        return res;
      })
      .catch(() => caches.match(request))
  );
});
