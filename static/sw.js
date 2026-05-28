/* LEVIX conservative service worker (Phase 3) */

const STATIC_CACHE = "levix-static-v6";
const OFFLINE_URL = "/static/offline.html";

const PRECACHE_URLS = [
  OFFLINE_URL,
  "/static/manifest.json?v=20260528f",
  "/manifest.webmanifest",
  "/static/favicon.png?v=20260528f",
  "/static/logo.png",
  "/static/global.css?v=20260528f",
  "/static/mobile-fixes.css?v=20260528f",
  "/static/pwa-install.js?v=20260528f",
  "/static/theme.js",
  "/static/i18n.js",
  "/static/icons/icon-192.png?v=20260528f",
  "/static/icons/icon-512.png?v=20260528f",
  "/static/icons/icon-maskable-192.png?v=20260528f",
  "/static/icons/icon-maskable-512.png?v=20260528f"
];

const NETWORK_FIRST_STATIC_PATHS = [
  "/static/manifest.json",
  "/static/favicon.png",
  "/static/global.css",
  "/static/mobile-fixes.css"
];

const NETWORK_ONLY_PREFIXES = [
  "/api/",
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
  "/plans",
  "/contact",
  "/auth/",
  "/session"
];

function isNetworkOnlyPath(pathname) {
  return NETWORK_ONLY_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) =>
        Promise.allSettled(
          PRECACHE_URLS.map((url) => cache.add(url))
        )
      )
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
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith("levix-static-") && key !== STATIC_CACHE)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Never cache non-GET requests.
  if (request.method !== "GET") {
    event.respondWith(fetch(request));
    return;
  }

  // Do not cache cross-origin requests.
  if (url.origin !== self.location.origin) {
    event.respondWith(fetch(request));
    return;
  }

  // Protect API/auth/session and user-sensitive pages from caching.
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

  // Keep install identity assets fresh after icon updates.
  if (
    NETWORK_FIRST_STATIC_PATHS.includes(url.pathname) ||
    url.pathname.startsWith("/static/icons/")
  ) {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.ok) {
            const copy = networkResponse.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy));
          }
          return networkResponse;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Static assets: cache-first.
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

  // HTML/doc pages: network-first, offline fallback.
  if (isDocumentRequest) {
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  // Default: network-only.
  event.respondWith(fetch(request));
});
