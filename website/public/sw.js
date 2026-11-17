/* Temporary same-origin retirement worker. Keep served at the legacy /sw.js. */
const legacyScope = new URL('/', self.location.origin).href;
const legacyScript = new URL('/sw.js', self.location.origin).href;
const isLegacy = self.location.href === legacyScript && self.registration.scope === legacyScope;
async function retireLegacy() {
  if (!isLegacy) return;
  const name = 'workbox-precache-v2-' + legacyScope;
  if ((await caches.keys()).includes(name)) {
    const cache = await caches.open(name);
    const keys = await cache.keys();
    const paths = keys.map(request => new URL(request.url));
    const has = path => paths.some(url => url.origin === self.location.origin && url.pathname === path);
    // Exact name alone is generic Workbox: require the legacy app's cached assets.
    if (has('/index.html') && has('/registerSW.js') && has('/images/family-car-agent-logo.png')
        && has('/icons/family-car-agent-192.png') && has('/manifest.webmanifest')) {
      const manifestKey = keys.find(request => new URL(request.url).pathname === '/manifest.webmanifest');
      const response = await cache.match(manifestKey);
      const manifest = await response?.json().catch(() => null);
      if (manifest?.name === 'Family Car Agent' && manifest?.id === '/' && manifest?.start_url === '/') {
        await caches.delete(name);
      }
    }
  }
  await self.registration.unregister();
}
self.addEventListener('install', event => {
  if (isLegacy) event.waitUntil(self.skipWaiting());
});
self.addEventListener('activate', event => {
  event.waitUntil(retireLegacy().catch(() => { /* Keep storage on uncertainty; next update can retry. */ }));
});
// No fetch/push handlers, clients.claim(), navigation, storage reset or new cache.
// Existing documents finish normally; subsequent navigation uses the network.
