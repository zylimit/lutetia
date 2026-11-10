import { watch } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { ApiError, getMe } from './api'
import { i18n, t } from './i18n'
import type { Key } from './i18n'
import Bundles from './pages/Bundles.vue'
import Manholes from './pages/Manholes.vue'
import Overview from './pages/Overview.vue'
import Plan from './pages/Plan.vue'
import SignIn from './pages/SignIn.vue'
import { session } from './session'

// Every path under /app/ is served index.html by the server (history fallback), so these routes are the whole map.
// Overview / Manholes get their content in Task 9.3, Bundles / Plan in Phase 10; until then they are placeholders.
export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/signin', name: 'signin', component: SignIn },
    { path: '/', name: 'overview', component: Overview },
    { path: '/manholes', name: 'manholes', component: Manholes },
    { path: '/bundles', name: 'bundles', component: Bundles },
    { path: '/plan', name: 'plan', component: Plan },
    // CSP probe of Task 9.1 (ECharts + Leaflet under the strict CSP); lazy so the shell does not carry the chart libraries.
    { path: '/csp-probe', name: 'csp-probe', component: () => import('./pages/CspProbe.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// Every page except sign-in first asks who is signed in; 401 -> sign-in with the way back in `next`.
router.beforeEach(async (to) => {
  if (to.name === 'signin') return true
  try {
    const me = await getMe({ redirectOn401: false })
    session.account = me.data.account
    session.checkFailed = false
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      session.account = null
      return { name: 'signin', query: { next: router.resolve(to).href } }
    }
    session.checkFailed = true // server down or offline: let the page load, the shell shows that the session could not be checked
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
