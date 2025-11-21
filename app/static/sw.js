const CACHE_NAME = 'school-guard-v5';
const urlsToCache = [
    '/static/manifest.json',
    '/static/icons/icon-192x192.png',
    '/static/icons/icon-512x512.png'
    // No cacheamos HTML dinámico para asegurar datos frescos
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache');
                return cache.addAll(urlsToCache);
            })
    );
});

self.addEventListener('fetch', event => {
    // Estrategia: Network First (Intentar red, si falla, buscar en caché si existe)
    // Para una app de seguridad en tiempo real, priorizamos siempre la red.
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request);
        })
    );
});