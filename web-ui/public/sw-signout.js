// Loaded by sw.js through importScripts (vite.config.ts workbox.importScripts). Sign out (src/offline.ts) posts
// {type: 'lutetia-signout'} before it empties the caches: from then on the API cache plugin refuses every write
// (cacheWillUpdate reads self.__lutetiaSignedOut), so an answer arriving late cannot rebuild the cache. The worker is
// unregistered right after, so the flag never needs resetting.
self.__lutetiaSignedOut = false
self.addEventListener('message', (event) => {
  if (!event.data || event.data.type !== 'lutetia-signout') return
  self.__lutetiaSignedOut = true
  const port = event.ports && event.ports[0]
  if (port) port.postMessage({ type: 'lutetia-signout-ack' })
})
