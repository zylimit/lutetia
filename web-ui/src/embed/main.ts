// Entry of embed.html, served at /embed/<widget> (lutetia/web/embed.py). No router, no AppShell, no service worker and no
// manifest: this file must never import offline.ts startOffline or the PWA registration (Phase 12, Design-Brief E1 ~ E3).
import { createApp } from 'vue'
import '../styles/fonts.css'
import '../styles/tokens.css'
import '../styles/base.css'
import { i18n, pickLang } from '../i18n'
import { RANGES } from '../range'
import type { Range } from '../range'
import { WIDGETS } from './data'
import type { Widget } from './data'
import EmbedApp from './EmbedApp.vue'

const DEFAULT_RANGE: Range = '7d'

const query = new URLSearchParams(window.location.search)
// Light theme by default (Design-Brief E1 ~ E3); the stored theme of the full app is not read here.
document.documentElement.dataset.theme = 'light'
// ?lang=en|fr from the host; otherwise the browser language. The full app's stored choice is not used and nothing is stored.
const lang = query.get('lang')
i18n.lang = lang === 'en' || lang === 'fr' ? lang : pickLang(null, navigator.language)
document.documentElement.lang = i18n.lang

const name = window.location.pathname.replace(/^\/embed\//, '')
const range = query.get('range')

if ((WIDGETS as readonly string[]).includes(name)) {
  createApp(EmbedApp, {
    widget: name as Widget,
    range: range && (RANGES as readonly string[]).includes(range) ? (range as Range) : DEFAULT_RANGE,
    deviceId: query.get('device_id') || null,
  }).mount('#embed')
} else {
  // The server answers 404 for any other name; reaching this means the page was opened some other way (dev server, /app/embed.html).
  console.error(`embed: unknown widget "${name}", expected one of ${WIDGETS.join(', ')}`)
}
