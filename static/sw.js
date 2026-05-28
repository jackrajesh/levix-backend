/* LEVIX PWA service worker — root scope, install-safe */

const STATIC_CACHE = "levix-static-v8";
const OFFLINE_URL = "/static/offline.html";

const PRECACHE_URLS = [
  OFFLINE_URL,
  "/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-192.png",
  "/static/icons/icon-maskable-512.png",
  "/static/favicon.png",
  "/static/global.css",
  "/static/mobile-fixes.css",
  "/static/pwa-install.js",
  "/static/pwa-install-ui.css"
];

const NETWORK_ONLY_PREFIXES = [
  "/api/",
  "/auth/",
  "/session",
  "/login",
  "/register",
  "/logout",
  "/forgot-password",
  "/reset-password",
  "/dashboard",
  "/levix-admin",
  "/settings",
  "/team",
  "/inbox",
  "/orders",
  "/sales",
  "/inventory",
  "/analytics",
  "/plans"
];

const NEVER_CACHE_PATHS = new Set([
  "/sw.js",
  "/manifest.webmanifest",
  "/static/manifest.json"
]);

function isNetworkOnlyPath(pathname) {
  return NETWORK_ONLY_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => Promise.allSettled(PRECACHE_URLS.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("levix-static-") && key !== STATIC_CACHE)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    event.respondWith(fetch(request));
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    event.respondWith(fetch(request));
    return;
  }

  if (NEVER_CACHE_PATHS.has(url.pathname)) {
    event.respondWith(fetch(request));
    return;
  }

  if (isNetworkOnlyPath(url.pathname)) {
    event.respondWith(
      fetch(request).catch(() => {
        if (request.mode === "navigate") {
          return caches.match(OFFLINE_URL);
        }
        return new Response("", { status: 503, statusText: "Offline" });
      })
    );
    return;
  }

  const isStaticAsset = url.pathname.startsWith("/static/");
  const isDocumentRequest = request.mode === "navigate" || request.destination === "document";

  if (isStaticAsset) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.ok) {
            const copy = networkResponse.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy));
          }
          return networkResponse;
        });
      })
    );
    return;
  }

  if (isDocumentRequest) {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  event.respondWith(fetch(request));
});
