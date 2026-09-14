const CACHE='freetify-v30';
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('install',event=>event.waitUntil(Promise.all([self.skipWaiting(),caches.open(CACHE).then(cache=>cache.addAll(['./','./index.html','./styles.css','./app.js','./manifest.webmanifest']))])));
self.addEventListener('fetch',event=>event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request))));
