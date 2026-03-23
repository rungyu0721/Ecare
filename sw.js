const CACHE_NAME = "ecare-pwa-v6";

const ASSETS = [
  "./",
  "./user.html",
  "./ecare.html",
  "./records.html",
  "./profile.html",

  "./styles.css",
  "./ecare.css",
  "./profile.css",

  "./app.js",
  "./ecare.js",
  "./records.js",
  "./profile.js",

  "./manifest.json"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  e.respondWith(
    caches.match(e.request).then((cached) => {
      if (cached) return cached;
      return fetch(e.request);
    })
  );
});