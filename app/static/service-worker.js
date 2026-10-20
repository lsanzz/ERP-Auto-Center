const CACHE = 'lshub-ui-v9';
const ASSETS = ['/static/theme.css', '/static/styles.css', '/static/design-system.css', '/static/ui.js',
  '/static/lshub.svg', '/static/lshub-icon.svg'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS))));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;
  if (!new URL(event.request.url).pathname.startsWith('/static/')) return;
  // Prefer current CSS/JS so a cached release cannot hide interface fixes.
  // Cached static assets remain available when the network is unavailable.
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok) {
      const copy = response.clone();
      event.waitUntil(caches.open(CACHE).then(cache => cache.put(event.request, copy)));
    }
    return response;
  }).catch(async error => {
    const cached = await caches.match(event.request);
    if (cached) return cached;
    throw error;
  }));
});
