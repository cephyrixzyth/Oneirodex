/* Retire the former authenticated VR cache worker without retaining private data. */
const RETIRED_CACHE = 'oneirodex-vr-v1';

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.delete(RETIRED_CACHE)
      .then(() => self.clients.claim())
      .then(() => self.registration.unregister()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'od-vr-retired') {
    event.waitUntil(caches.delete(RETIRED_CACHE).then(() => {
      event.ports[0]?.postMessage('od-vr-retired');
    }));
    return;
  }
  if (event.data === 'od-clear-caches' || event.data?.type === 'od-clear-caches') {
    event.waitUntil(caches.delete(RETIRED_CACHE));
  }
});
