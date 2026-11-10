// Theme choice: dark, light or projector. First visit follows prefers-color-scheme; a manual choice is remembered in localStorage.
import { reactive } from 'vue'

export type Theme = 'dark' | 'light' | 'projector'
export const THEMES: readonly Theme[] = ['dark', 'light', 'projector']
export const THEME_KEY = 'lutetia.theme'

export function pickTheme(stored: string | null, prefersLight: boolean): Theme {
  if (stored === 'dark' || stored === 'light' || stored === 'projector') return stored
  return prefersLight ? 'light' : 'dark'
}

function readStored(): string | null {
  try {
    return localStorage.getItem(THEME_KEY)
  } catch {
    return null // storage blocked: the choice just does not persist
  }
}

export const themeState = reactive<{ theme: Theme }>({
  theme: pickTheme(readStored(), window.matchMedia('(prefers-color-scheme: light)').matches),
})

function apply(): void {
  document.documentElement.dataset.theme = themeState.theme
}

export function setTheme(theme: Theme): void {
  themeState.theme = theme
  apply()
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // not persisted; the theme still applies for this page view
  }
}

export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]
}

apply()
