/** Whick Remote Portal — installable PWA shell (no offline cache yet) */
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', () => {
  /* network-first — icons/manifest only for install criteria */
});
