// Service Worker for Bitvavo Trading Bot PWA
const CACHE_NAME = 'bitvavo-bot-v3';
const STATIC_ASSETS = [
    '/static/css/premium_trading.css?v=2',
    '/static/css/premium_cards.css?v=2',
    '/static/css/faang_upgrades.css?v=2',
    '/static/css/faang_ultimate.css?v=2',
    '/static/css/apex_design.css?v=2',
    '/static/js/dashboard.js',
    '/static/js/faang_upgrades.js',
    '/static/js/faang_ultimate.js',
    '/static/js/apex_interactions.js',
    '/static/manifest.json'
];

// Install - cache static assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(STATIC_ASSETS).catch(() => {
                // Some assets may not be available, skip
                console.log('[SW] Some assets could not be cached');
            });
        })
    );
    self.skipWaiting();
});

// Activate - clean old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
            );
        })
    );
    self.clients.claim();
});

// Fetch - network first, then cache
self.addEventListener('fetch', (event) => {
    // Skip WebSocket and API requests
    if (event.request.url.includes('/api/') ||
        event.request.url.includes('/socket.io/') ||
        event.request.method !== 'GET') {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then(response => {
                // Cache successful responses
                if (response.ok && event.request.url.includes('/static/')) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() => {
                // Fallback to cache
                return caches.match(event.request);
            })
    );
});
