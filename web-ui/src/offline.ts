/// <reference types="vite-plugin-pwa/client" />
// Offline side of the PWA (Task 11.1, SC-11, DFX privacy): registers the service worker once someone is signed in, tells the
// pages when an API answer came from the worker's cache, and empties the caches on Sign out, on an expired session and
// when another account signs in on the same device.
import { reactive } from 'vue'
import { registerSW } from 'virtual:pwa-register'
import { ACCOUNT_KEY, mustClearForAccount } from './account-switch'

// Same literals as vite.config.ts / public/sw-signout.js (the worker build runs in Node and cannot import this module).
export const API_CACHE = 'lutetia-api'
export const CACHE_HEADER = 'X-Lutetia-Cache'
const SIGNOUT_MESSAGE = 'lutetia-signout'
const SIGNOUT_ACK_MS = 1000

export const offline = reactive({
  /** Data on screen includes the worker's saved copy (network down, 5xx, or slower than its timeout). */
  cached: false,
})

// A refresh round (live.ts) is all-or-nothing: one saved answer in it marks the screen as offline; only a fully fresh
// round clears the flag. Outside a round (a page's own request) a fresh answer clears it directly.
let round: { hit: boolean } | null = null

export function beginRound(): void {
  round = { hit: false }
}
/** ok = every request of the round answered. */
export function endRound(ok: boolean): void {
  if (round && ok && !round.hit) offline.cached = false
  round = null
}

/** apiGet calls this for every answer it reads. */
export function noteResponse(resp: Response): void {
  const hit = resp.headers.get(CACHE_HEADER) === 'hit'
  if (hit) {
    offline.cached = true
    if (round) round.hit = true
  } else if (!round) offline.cached = false
}

function cacheStorage(): CacheStorage | null {
  return typeof caches === 'undefined' ? null : caches // no Cache Storage (plain http on a LAN address, old browser)
}

let registered = false

/** Called by the route guard after /api/v1/me answered 200. Registering twice is a no-op. */
export function startOffline(): void {
  if (registered || !('serviceWorker' in navigator)) return
  registered = true
  registerSW({
    immediate: true,
    onRegisterError(e: unknown) {
      console.error('service worker registration failed: the app works, but not offline', e)
    },
  })
}

/** Whether the API cache holds anything: offline without it there is nothing to show, so the guard sends people to sign-in. */
export async function hasApiCache(): Promise<boolean> {
  const store = cacheStorage()
  if (!store || !(await store.has(API_CACHE))) return false
  return (await (await store.open(API_CACHE)).keys()).length > 0
}

/** Session expired (401) or another account: drop the saved API answers. The app shell stays for sign-in. */
export async function clearApiCache(): Promise<void> {
  const store = cacheStorage()
  if (!store) return
  try {
    await store.delete(API_CACHE)
  } catch (e) {
    console.error('could not clear the offline API cache', e)
  }
  offline.cached = false
}

/** After /me said who is signed in: a different (or unknown) previous account on this device loses its saved answers. */
export async function rememberAccount(account: string): Promise<void> {
  let previous: string | null = null
  try {
    previous = localStorage.getItem(ACCOUNT_KEY)
  } catch (e) {
    console.warn('account name not readable from storage: clearing the saved answers to be safe', e)
  }
  if (mustClearForAccount(previous, account)) await clearApiCache()
  try {
    localStorage.setItem(ACCOUNT_KEY, account)
  } catch (e) {
    console.warn('account name not stored (storage blocked): the next sign-in clears the saved answers again', e)
  }
}

/** Tell the worker to refuse cache writes from now on; resolves on its ack, or after 1 s without one (logged). */
async function stopCacheWrites(): Promise<void> {
  const worker = 'serviceWorker' in navigator ? navigator.serviceWorker.controller : null
  if (!worker) return
  const channel = new MessageChannel()
  const acked = await new Promise<boolean>((resolve) => {
    const timer = window.setTimeout(() => resolve(false), SIGNOUT_ACK_MS)
    channel.port1.onmessage = () => {
      window.clearTimeout(timer)
      resolve(true)
    }
    worker.postMessage({ type: SIGNOUT_MESSAGE }, [channel.port2])
  })
  channel.port1.close()
  if (!acked) console.warn(`service worker did not confirm sign-out within ${SIGNOUT_ACK_MS} ms: clearing the caches anyway`)
}

/** Sign out: stop cache writes, then every cache (API answers and the app shell) and the worker itself, so this phone keeps
 * nothing (DFX privacy). The worker is registered again on the next successful sign-in. Throws when a cache could not be
 * deleted. */
export async function clearEverything(): Promise<void> {
  await stopCacheWrites()
  const store = cacheStorage()
  if (store) {
    const names = await store.keys()
    const results = await Promise.all(names.map((n) => store.delete(n)))
    if (results.some((ok) => !ok)) throw new Error(`could not delete every offline cache (${names.join(', ')})`)
  }
  if ('serviceWorker' in navigator) {
    const regs = await navigator.serviceWorker.getRegistrations()
    await Promise.all(regs.map((r) => r.unregister()))
  }
  registered = false
  offline.cached = false
}
