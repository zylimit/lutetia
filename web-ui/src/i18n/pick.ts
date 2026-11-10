// Pure language choice (no DOM access, so it can be unit-tested outside a browser).
export type Lang = 'en' | 'fr'

/** Stored choice wins; otherwise the first language in the browser's preference list that is English or French
 * (same rule as the ops dashboard's Accept-Language reading); none of them: en (Design-Brief 6.1). */
export function pickLang(stored: string | null, browser: string | readonly string[] | undefined): Lang {
  if (stored === 'en' || stored === 'fr') return stored
  const list = typeof browser === 'string' ? [browser] : (browser ?? [])
  for (const tag of list) {
    const primary = tag.toLowerCase().split('-')[0]
    if (primary === 'fr' || primary === 'en') return primary
  }
  return 'en'
}
