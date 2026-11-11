// Service worker minimal : rend l'appli installable et garde l'interface en cache.
const CACHE = "studio-v2";
const SHELL = ["/", "/static/style.css?v=2", "/static/app.js?v=2", "/static/icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname === "/share") return;
  // Réseau d'abord, cache si hors ligne
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok && (url.pathname === "/" || url.pathname.startsWith("/static/"))) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(url.pathname === "/" ? "/" : e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(url.pathname === "/" ? "/" : e.request))
  );
});
