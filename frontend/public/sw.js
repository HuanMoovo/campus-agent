/* Offline shell for the installable web client (Android/iOS/desktop browsers).
 *
 * Only same-origin GET requests are cached; API traffic always goes to the network so the
 * question-answering flow can never be served from a stale cache. The desktop app never
 * registers this worker (main.ts skips it when the Electron bridge is present). */
const CACHE = 'mens-shell-__MENS_VERSION__'
const SHELL = ['./', './index.html', './favicon.png', './icon-192.png', './icon-512.png', './manifest.webmanifest']

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', event => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api')) return
  event.respondWith((async () => {
    const cache = await caches.open(CACHE)
    const cached = await cache.match(request)
    if (cached) return cached
    try {
      const response = await fetch(request)
      if (response.ok && response.type === 'basic') cache.put(request, response.clone())
      return response
    } catch (error) {
      if (request.mode === 'navigate') {
        const shell = await cache.match('./index.html')
        if (shell) return shell
      }
      throw error
    }
  })())
})
