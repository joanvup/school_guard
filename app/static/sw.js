const CACHE_NAME = 'school-guard-v7';
const PRECACHE_URLS = [
    '/static/manifest.json',
    '/static/icons/icon-192x192.png',
    '/static/icons/icon-512x512.png',
    '/static/icons/icon-maskable-512x512.png',
    '/static/icons/apple-touch-icon-180x180.png',
    '/static/css/main.css',
    '/static/css/fontawesome.css',
    '/static/js/base.js',
    '/static/js/api.js',
    '/static/js/chart.min.js',
    '/static/js/qrcode.min.js',
    '/static/js/html5-qrcode.min.js',
    '/static/assets/avatar.png',
    '/static/webfonts/fa-brands-400.woff2',
    '/static/webfonts/fa-regular-400.woff2',
    '/static/webfonts/fa-solid-900.woff2',
    '/static/webfonts/fa-v4compatibility.woff2'
];
const PRECACHE_PATHS = new Set(PRECACHE_URLS.map((url) => new URL(url, self.location.origin).pathname));

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(PRECACHE_URLS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const request = event.request;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    // Solo estáticos precacheados: HTML, APIs y medios privados siempre van a la red.
    if (!PRECACHE_PATHS.has(url.pathname)) return;

    event.respondWith(
        caches.match(request).then(cached => {
            if (cached) return cached;
            return fetch(request).then(response => {
                if (response.ok) {
                    const copy = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
                }
                return response;
            });
        })
    );
});
