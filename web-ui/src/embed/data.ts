// Data of the embedded widgets: the same /api/v1 readers and the same shared `live` store as the pages (so EventRow shows the
// IMEI and Banner shows offline / error / delayed), but a 401 never navigates: it turns the widget into the sign-in prompt
// (CMP-11), and the next focus or visible tab tries again. 60 s refresh like Overview. No offline cache (Design-Brief E1–E3).
import { reactive } from 'vue'
import { ApiError } from '../api'
import type { GetOptions } from '../api'
import { REFRESH_MS, live, pickLatest } from '../live'
import { RANGE_HOURS } from '../range'
import type { Range } from '../range'
import { TIMEOUT_MS, getEventsSince, getManholes, getSummary } from '../resources'
import type { FallEvent } from '../resources'
import { loadEmbedConfig } from './host'

/** The widget names; lutetia/web/embed.py WIDGETS lists the same three (any other /embed path is 404 there). */
export type Widget = 'fall-timeline' | 'manhole-map' | 'security-summary'
export const WIDGETS: readonly Widget[] = ['fall-timeline', 'manhole-map', 'security-summary']

const OPTS: GetOptions = { redirectOn401: false, timeoutMs: TIMEOUT_MS }

export interface EmbedQuery {
  range: Range
  deviceId: string | null
}

export const embed = reactive({
  signedOut: false,
  events: [] as FallEvent[], // fall-timeline only: suspicious first, then newest start first
})

function forget(): void {
  live.summary = null
  live.asOf = null
  live.manholes = []
  live.loaded = false
  embed.events = []
}

async function refresh(withEvents: boolean, q: EmbedQuery): Promise<void> {
  if (live.loading) return
  live.loading = true
  void loadEmbedConfig()
  try {
    const [summary, manholes, events] = await Promise.all([
      getSummary(OPTS),
      getManholes(OPTS),
      withEvents ? getEventsSince(RANGE_HOURS[q.range], q.deviceId ?? undefined, OPTS) : Promise.resolve([]),
    ])
    live.summary = summary.data
    live.asOf = summary.as_of
    live.manholes = manholes.items
    embed.events = pickLatest(events, events, manholes.items, events.length) // same suspicious-first rule as Overview
    live.loaded = true
    live.error = null
    embed.signedOut = false
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(-1, e instanceof Error ? e.message : String(e))
    if (err.status === 401) {
      embed.signedOut = true
      live.error = null
      forget() // nothing of the previous session stays on screen
    } else {
      live.error = err
      console.error('embed: refresh failed', err)
    }
  } finally {
    live.loading = false
  }
}

/** Starts the refresh loop; returns the stop function. */
export function startEmbedData(withEvents: boolean, q: EmbedQuery): () => void {
  const run = () => void refresh(withEvents, q)
  // Back from the sign-in tab: the window gets focus or the tab turns visible again; retry at once instead of in up to 60 s.
  const retry = () => {
    if (embed.signedOut && document.visibilityState === 'visible') run()
  }
  const onOnline = () => {
    live.online = true
    run()
  }
  const onOffline = () => (live.online = false)
  window.addEventListener('focus', retry)
  document.addEventListener('visibilitychange', retry)
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  const timer = window.setInterval(run, REFRESH_MS)
  run()
  return () => {
    window.clearInterval(timer)
    window.removeEventListener('focus', retry)
    document.removeEventListener('visibilitychange', retry)
    window.removeEventListener('online', onOnline)
    window.removeEventListener('offline', onOffline)
  }
}
