// FoodLog service worker — registration only, no caching or fetch interception.
// Exists so browsers consider the app PWA-installable; all requests go to network.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
