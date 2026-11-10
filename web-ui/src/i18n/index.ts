// A small reactive dictionary instead of vue-i18n (YAGNI: two languages, flat keys, no plural rules yet).
import { reactive } from 'vue'
import { en } from './en'
import type { Key } from './en'
import { fr } from './fr'

export type Lang = 'en' | 'fr'
export type { Key }
export const LANG_KEY = 'lutetia.lang'
const DICTS: Record<Lang, Partial<Record<Key, string>>> = { en, fr }

/** Stored choice wins; otherwise a browser language starting with fr gives fr, anything else en (Design-Brief 6.1). */
export function pickLang(stored: string | null, browser: string | undefined): Lang {
  if (stored === 'en' || stored === 'fr') return stored
  return (browser ?? '').toLowerCase().startsWith('fr') ? 'fr' : 'en'
}

function readStored(): string | null {
  try {
    return localStorage.getItem(LANG_KEY)
  } catch {
    return null // storage blocked (private window): the choice just does not persist
  }
}

export const i18n = reactive<{ lang: Lang }>({ lang: pickLang(readStored(), navigator.language) })

export function setLang(lang: Lang): void {
  i18n.lang = lang
  document.documentElement.lang = lang
  try {
    localStorage.setItem(LANG_KEY, lang)
  } catch {
    // not persisted; the switch still applies for this page view
  }
}

/** A string missing in the current language shows the English one, never the key (Design-Brief 6.1). */
export function t(key: Key): string {
  return DICTS[i18n.lang][key] ?? en[key]
}

document.documentElement.lang = i18n.lang
