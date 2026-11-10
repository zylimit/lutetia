// Which CMP-12 banner shows (Design-Brief: at most one). Pure, so it is unit-tested without the browser (banner.test.ts).
export type BannerKind = 'error' | 'stale' | 'offline'

export interface BannerInput {
  error: boolean // the last refresh failed
  stale: boolean // the collector says the data is delayed
  offline: boolean // navigator.onLine is false, or the data on screen came from the worker's cache
}

/** The time on the offline banner: the page's own resource (Bundles trackers, Plan work orders) when the page set one,
 * otherwise the shared security summary (Overview, Manholes). */
export function offlineAsOf(pageAsOf: string | null, liveAsOf: string | null): string | null {
  return pageAsOf ?? liveAsOf
}

/** Offline wins over everything: delay cannot be known without a connection, the time of the saved data is what counts
 * (Decisions 2026-11-10, Task 11.1). Online: error > data delayed. */
export function pickBanner(s: BannerInput): BannerKind | null {
  if (s.offline) return 'offline'
  if (s.error) return 'error'
  if (s.stale) return 'stale'
  return null
}
