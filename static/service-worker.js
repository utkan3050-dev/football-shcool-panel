const CACHE_NAME = "futbol-okulu-v1";

const STATIC_ASSETS = [
    "/static/style.css",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
    "/manifest.webmanifest"
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
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

self.addEventListener("fetch", (event) => {
    const request = event.request;

    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);

    if (url.origin !== self.location.origin) {
        return;
    }

    // Kullanıcı verileri ve panel ekranları cache'lenmez; her zaman güncel sunucu verisi alınır.
    if (
        !url.pathname.startsWith("/static/")
        && url.pathname !== "/manifest.webmanifest"
    ) {
        event.respondWith(fetch(request));
        return;
    }

    event.respondWith(
        caches.match(request).then((cached) => {
            return cached || fetch(request).then((response) => {
                const copy = response.clone();
                caches.open(CACHE_NAME)
                    .then((cache) => cache.put(request, copy));
                return response;
            });
        })
    );
});
