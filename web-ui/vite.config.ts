import { defineConfig } from 'vite'
import type { Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

// Theme colours are DESIGN.md tokens (manifest and meta tags cannot read CSS variables):
// colors.surface #1C2025 = the top bar, so the status bar blends in; colors.neutral #15181C = the page background (base.css body).
const THEME = '#1C2025'
const BACKGROUND = '#15181C'

// The runtime cache of API answers. API_CACHE and the X-Lutetia-Cache header below are read back by src/offline.ts (same
// literals there: this file runs in Node and cannot share a module with the browser code).
const API_CACHE = 'lutetia-api'
// Distinct GET URLs the SPA asks for, counted on 2026-11-10: summary, manholes, latest events, 4 event windows, per manhole
// (12) series x 2 ranges + 30-day events = 36, bundles + one 7-day track each, POI list per filter set, segments per opened
// POI, SLA templates, list pages beyond the first. 200 leaves room; the oldest entry goes first when it is reached.
const API_CACHE_ENTRIES = 200
const API_CACHE_MAX_AGE_S = 7 * 24 * 3600
// Under the 10 s request timeout of the pages (resources.ts TIMEOUT_MS): a weak signal falls back to the last answer first.
const API_NETWORK_TIMEOUT_S = 5

// vite-plugin-pwa adds its manifest link to every HTML page of the build; the embedded widgets (embed.html, Phase 12) must not
// carry it (no install prompt, no PWA inside a host page). Runs after the PWA plugin and fails the build if anything remains.
function embedWithoutPwa(): Plugin {
  return {
    name: 'lutetia:embed-without-pwa',
    enforce: 'post',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        if (ctx.path !== '/embed.html') return html
        const out = html.replace(/\s*<link rel="manifest"[^>]*>/g, '')
        if (/manifest|registerSW|serviceWorker/.test(out)) throw new Error('embed.html still references the PWA (manifest / worker)')
        return out
      },
    },
  }
}

export default defineConfig({
  base: '/app/',
  plugins: [
    vue(),
    // Task 11.1 (SC-11): installable shell + last API answers for offline use. The worker lives at /app/sw.js, so its scope is
    // /app/ only: /embed/* (Phase 12, "embedded widgets keep no offline cache") is never controlled by it.
    VitePWA({
      strategies: 'generateSW',
      // autoUpdate: a read-only dashboard has nothing to lose on reload and no "new version" prompt in the design.
      registerType: 'autoUpdate',
      // false: the worker is registered from router.ts only once /api/v1/me said someone is signed in (offline.ts startOffline),
      // so a signed-out browser (after Sign out cleared every cache and unregistered it) keeps nothing.
      injectRegister: false,
      scope: '/app/',
      manifestFilename: 'manifest.webmanifest',
      includeAssets: ['icons/apple-touch-icon.png'],
      manifest: {
        id: '/app/',
        name: 'Ariane · Copper Watch',
        short_name: 'Ariane · Copper Watch',
        description: 'Copper theft watch: manholes, cable bundles and work orders.',
        lang: 'en',
        display: 'standalone',
        start_url: '/app/',
        scope: '/app/',
        theme_color: THEME,
        background_color: BACKGROUND,
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // The app shell: the whole build (JS, CSS, fonts, icons, index.html). Map tiles and API data are not precached.
        // (manifest icons, the manifest and includeAssets are added by the plugin itself; listing png here would list them twice)
        globPatterns: ['**/*.{js,css,html,woff2,woff,svg}'],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
        // Every /app/ navigation is the SPA (history fallback); file paths and the server's own pages are not.
        navigateFallback: '/app/index.html',
        navigateFallbackAllowlist: [/^\/app\//],
        navigateFallbackDenylist: [/^\/app\/assets\//, /^\/api\//, /^\/login/, /^\/logout/, /^\/embed\//],
        // Workbox runtime is bundled into workbox-<hash>.js next to sw.js (no CDN importScripts: CSP script-src 'self').
        inlineWorkboxRuntime: false,
        // Local listener for the Sign out message (public/sw-signout.js, served from /app/ like sw.js).
        importScripts: ['sw-signout.js'],
        runtimeCaching: [
          {
            // GET /api/v1/* except /me: the route guard tells "offline" from "signed out" itself (router.ts), so who is
            // signed in is never answered from a cache.
            urlPattern: ({ url, sameOrigin }) => sameOrigin && url.pathname.startsWith('/api/v1/') && url.pathname !== '/api/v1/me',
            method: 'GET',
            handler: 'NetworkFirst',
            options: {
              cacheName: API_CACHE,
              networkTimeoutSeconds: API_NETWORK_TIMEOUT_S,
              expiration: { maxEntries: API_CACHE_ENTRIES, maxAgeSeconds: API_CACHE_MAX_AGE_S, purgeOnQuotaError: true },
              cacheableResponse: { statuses: [200] },
              // Plugin functions are copied into sw.js as source text: they must not use anything from this file.
              plugins: [
                {
                  // DFX-Spec §3: a 502 / 504 from nginx (or any 5xx) is "offline" for the SPA: throwing here makes
                  // NetworkFirst answer from the cache instead (no saved copy -> the page sees a network error).
                  fetchDidSucceed: async ({ response }) => {
                    if (response.status >= 500) throw new Error(`server answered ${response.status}, using the saved copy`)
                    return response
                  },
                  // After Sign out started (public/sw-signout.js sets the flag), a late network answer must not refill the
                  // cache that is about to be emptied.
                  cacheWillUpdate: async ({ response }) => ((self as unknown as { __lutetiaSignedOut?: boolean }).__lutetiaSignedOut ? null : response),
                  // One entry per resource (SC-11 "only the latest"): `since` is "now minus a window", a new URL each minute;
                  // key it by the window length instead, so each refresh replaces the previous answer of the same window.
                  cacheKeyWillBeUsed: async ({ request }) => {
                    const u = new URL(request.url)
                    const since = u.searchParams.get('since')
                    if (!since) return request
                    const hours = Math.round((Date.now() - Date.parse(since)) / 3_600_000)
                    if (!Number.isFinite(hours)) return request
                    u.searchParams.set('since', `window-${hours}h`)
                    return u.href
                  },
                  // Only called when NetworkFirst falls back to the cache: mark the answer so the page can say "Offline".
                  cachedResponseWillBeUsed: async ({ cachedResponse }) => {
                    if (!cachedResponse) return cachedResponse
                    const headers = new Headers(cachedResponse.headers)
                    headers.set('X-Lutetia-Cache', 'hit')
                    return new Response(await cachedResponse.blob(), { status: cachedResponse.status, statusText: cachedResponse.statusText, headers })
                  },
                },
              ],
            },
          },
        ],
      },
    }),
    embedWithoutPwa(), // after VitePWA: its manifest link must already be in the page to be taken out
  ],
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    // Never inline assets as data: URIs: the /app/ CSP has font-src 'self' (no data:), so inlined fonts would be refused.
    assetsInlineLimit: 0,
    // Two pages from one build (Phase 12): the dashboard (index.html) and the embedded widgets (embed.html, served by the
    // server at /embed/<name>, assets under /app/assets). embed.html gets no manifest link and never registers the worker.
    rolldownOptions: {
      input: { main: 'index.html', embed: 'embed.html' },
    },
  },
})
