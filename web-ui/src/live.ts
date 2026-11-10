// Shared, self-refreshing security data for Overview and Manholes: summary, every manhole, the newest events.
// One 60 s timer while at least one page uses it (Design-Brief 5.1: background refresh, no full reload, old data kept on error).
import { computed, reactive } from 'vue'
import { ApiError } from './api'
import { eventKey, getEventsSince, getLatestEvents, getManholes, getSummary } from './resources'
import type { FallEvent, Manhole, Summary } from './resources'

export const REFRESH_MS = 60_000
export const LATEST_N = 3
const PULSE_TOTAL_MS = 3 * 600 + 100 // DESIGN.md Motion: three pulses of 600 ms, then the marker rests

export const live = reactive({
  summary: null as Summary | null,
  asOf: null as string | null, // as_of of the last successful summary
  manholes: [] as Manhole[],
  latest: [] as FallEvent[],
  loaded: false, // at least one refresh succeeded
  loading: false,
  error: null as ApiError | null, // the last refresh failed (old data stays on screen)
  online: navigator.onLine,
  pulse: [] as string[], // device ids whose marker pulses right now
  tick: 0, // bumps after every successful refresh, so pages can reload their own lists
})

let knownEvents: Set<string> | null = null // null until the first load: nothing is "new" on the first paint
let timer = 0
let users = 0
let pulseTimer = 0

function reducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function markNew(events: FallEvent[]): void {
  const keys = new Set(events.map(eventKey))
  const fresh = knownEvents ? events.filter((e) => !knownEvents!.has(eventKey(e))).map((e) => e.device_id) : []
  knownEvents = knownEvents ? new Set([...knownEvents, ...keys]) : keys
  if (!fresh.length || reducedMotion()) return // reduced motion: the colour and shape change alone (DESIGN.md Motion)
  live.pulse = [...new Set(fresh)]
  window.clearTimeout(pulseTimer)
  pulseTimer = window.setTimeout(() => (live.pulse = []), PULSE_TOTAL_MS)
}

/** Offline with an unfinished event: the most suspicious case, kept on top and always shown (Decisions 2026-11-10). */
export function isSuspicious(e: FallEvent, status: string | undefined): boolean {
  return e.ended_at === null && status === 'offline'
}

/** The suspicious events first (as many as there are, up to n), then the newest others, each group newest start first. */
export function pickLatest(newest: FallEvent[], open: FallEvent[], manholes: Manhole[], n: number): FallEvent[] {
  const offline = new Set(manholes.filter((m) => m.status === 'offline').map((m) => m.device_id))
  const byStart = (a: FallEvent, b: FallEvent) => Date.parse(b.started_at) - Date.parse(a.started_at)
  const first = open.filter((e) => e.ended_at === null && offline.has(e.device_id)).sort(byStart).slice(0, n)
  const taken = new Set(first.map(eventKey))
  const rest = newest.filter((e) => !taken.has(eventKey(e))).sort(byStart)
  return [...first, ...rest].slice(0, n)
}

/** Unfinished events overlap any window, so a 1 h window returns all of them (queries_v1 fall_event_page). */
async function openEvents(manholes: Manhole[]): Promise<FallEvent[]> {
  if (!manholes.some((m) => m.status === 'offline' && m.open_event)) return []
  return (await getEventsSince(1)).filter((e) => e.ended_at === null)
}

export async function refresh(): Promise<void> {
  if (live.loading) return
  live.loading = true
  try {
    const [summary, manholes, latest] = await Promise.all([getSummary(), getManholes(), getLatestEvents(LATEST_N)])
    live.summary = summary.data
    live.asOf = summary.as_of
    live.manholes = manholes.items
    const latest3 = pickLatest(latest, await openEvents(manholes.items), manholes.items, LATEST_N)
    markNew(latest3)
    live.latest = latest3
    live.loaded = true
    live.error = null
    live.tick++
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(-1, e instanceof Error ? e.message : String(e))
    if (err.status !== 401) {
      live.error = err // 401 already sends the browser to sign-in
      console.error('security data refresh failed', err)
    }
  } finally {
    live.loading = false
  }
}

function onOnline(): void {
  live.online = true
  void refresh()
}
function onOffline(): void {
  live.online = false
}

/** Pages call this in onMounted and the returned function in onBeforeUnmount. */
export function useLive(): () => void {
  if (users++ === 0) {
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    timer = window.setInterval(() => void refresh(), REFRESH_MS)
    void refresh()
  }
  return () => {
    if (--users > 0) return
    window.clearInterval(timer)
    window.removeEventListener('online', onOnline)
    window.removeEventListener('offline', onOffline)
  }
}

export type BannerKind = 'error' | 'stale' | 'offline'

/** Design-Brief CMP-12: at most one banner, the most severe wins: error > data delayed > offline. */
export const banner = computed<BannerKind | null>(() => {
  if (live.error && live.online) return 'error'
  if (live.summary?.collector.stale) return 'stale'
  if (!live.online) return 'offline'
  return null
})

export function byId(id: string): Manhole | undefined {
  return live.manholes.find((m) => m.device_id === id)
}

/** What a manhole is called on screen: its IMEI (Spec: `name` holds the IMEI); the device id (ThingsBoard UUID in
 * production) only when the name is missing. */
export function imei(id: string): string {
  return byId(id)?.name || id
}
