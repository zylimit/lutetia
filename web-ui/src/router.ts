import { watch } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { ApiError, getMe } from './api'
import { i18n, t } from './i18n'
import type { Key } from './i18n'
import Bundles from './pages/Bundles.vue'
import Overview from './pages/Overview.vue'
import SignIn from './pages/SignIn.vue'
import { clearApiCache, hasApiCache, rememberAccount, startOffline } from './offline'
import { session } from './session'

// Every path under /app/ is served index.html by the server (history fallback), so these routes are the whole map.
// Overview / Manholes get their content in Task 9.3, Bundles / Plan in Phase 10; until then they are placeholders.
export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/signin', name: 'signin', component: SignIn },
    { path: '/', name: 'overview', component: Overview },
    // lazy: the drawer's charts (ECharts) load only when someone opens the Manholes page
    { path: '/manholes', name: 'manholes', component: () => import('./pages/Manholes.vue') },
    { path: '/bundles', name: 'bundles', component: Bundles },
    // lazy too: the Plan charts (ECharts) load only when someone opens the Plan page
    { path: '/plan', name: 'plan', component: () => import('./pages/Plan.vue') },
    // CSP probe of Task 9.1 (ECharts + Leaflet under the strict CSP); lazy so the shell does not carry the chart libraries.
    { path: '/csp-probe', name: 'csp-probe', component: () => import('./pages/CspProbe.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// Every page except sign-in first asks who is signed in; 401 -> sign-in with the way back in `next`.
const ME_TIMEOUT_MS = 5_000

// /me is never answered from the offline cache (vite.config.ts): "offline" and "signed out" are told apart here.
router.beforeEach(async (to) => {
  if (to.name === 'signin') {
    await clearApiCache() // whoever lands here is not signed in (Sign out, expired session): no saved answers stay behind
    return true
  }
  try {
    // 5 s: a dead signal that the browser still calls "online" becomes the offline branch below (ApiError 0), not a hang
    const me = await getMe({ redirectOn401: false, timeoutMs: ME_TIMEOUT_MS })
    session.account = me.data.account
    session.checkFailed = false
    await rememberAccount(me.data.account) // another account on this device: the previous one's saved answers go
    startOffline()
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      session.account = null
      await clearApiCache()
      return { name: 'signin', query: { next: router.resolve(to).href } }
    }
    if (e instanceof ApiError && e.status === 0) {
      // No connection. With saved answers the page shows them under the "Offline" banner (SC-11); without any (signed out,
      // never loaded) there is nothing to show, so sign-in, which says that signing in needs a connection.
      if (!(await hasApiCache())) return { name: 'signin', query: { next: router.resolve(to).href } }
      session.checkFailed = false
      console.warn('GET /api/v1/me unreachable: showing the saved data offline')
      return true
    }
    session.checkFailed = true // server answered with an error: let the page load, the shell shows that the session could not be checked
    console.error('GET /api/v1/me failed', e)
  }
  return true
})

// Browser tab title: brand plus the current page (the sign-in page uses its own heading); follows the language switch.
const BRAND = 'Ariane · Copper Watch'
const TITLE_KEYS: Record<string, Key> = { signin: 'signin', overview: 'overview', manholes: 'manholes', bundles: 'bundles', plan: 'plan' }
function updateTitle(): void {
  const key = TITLE_KEYS[String(router.currentRoute.value.name ?? '')]
  document.title = key ? `${BRAND} — ${t(key)}` : BRAND
}
router.afterEach(updateTitle)
watch(() => i18n.lang, updateTitle)
