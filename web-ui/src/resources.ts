// Typed readers for the /api/v1 resources the security pages use. Field names are exactly those of lutetia/web/openapi.json.
import { apiGet } from './api'
import type { Envelope, ListEnvelope } from './api'

/** Priority order, first match wins (progress Decisions 2026-11-10): inactive > offline > moving > moved > quiet. */
export type ManholeStatus = 'inactive' | 'offline' | 'moving' | 'moved' | 'quiet'
export const STATUSES: readonly ManholeStatus[] = ['inactive', 'offline', 'moving', 'moved', 'quiet']

export interface Summary {
  manholes: {
    total: number // in use = moved_24h + offline + quiet (moving is part of moved_24h)
    inactive: number
    all: number // total + inactive
    moved_24h: number
    moving: number
    offline: number
    offline_with_open_event: number
    quiet: number
  }
  bundles: { trackers: number; online: number; last_position_at: string | null }
  pois: { count: number; with_segments: number; planned_tonnes: number; without_weight: number } | null // null without poi:read
  collector: { updated_at: string | null; stale: boolean }
}

export interface Manhole {
  device_id: string
  name: string | null
  status: ManholeStatus | string // the contract allows statuses this client does not know yet
  open_event: boolean
  volt: number | null
  rsrp: number | null
  last_seen: string | null
  lat: number | null
  lon: number | null
  location_verified: boolean
}

export interface FallEvent {
  device_id: string
  started_at: string
  ended_at: string | null
  flips: number
  duration_sec: number | null
}

export interface SeriesPoint {
  at: string
  value: number | null
}

export interface ManholeSeries {
  device_id: string
  days: number
  hourly: boolean
  volt: SeriesPoint[]
  rsrp: SeriesPoint[]
  truncated: boolean
}

export const TIMEOUT_MS = 10_000
const PAGE = 1000
const MAX_PAGES = 20 // 20 000 rows: far beyond the project's dozen manholes; reaching it is reported, not silently cut

/** Every page of a list resource. */
export async function all<T>(path: string, params: Record<string, string | number>): Promise<{ items: T[]; asOf: string }> {
  const items: T[] = []
  let cursor: string | null = null
  let asOf = ''
  for (let n = 0; n < MAX_PAGES; n++) {
    const q: Record<string, string | number> = { ...params, limit: PAGE }
    if (cursor) q.cursor = cursor
    const page: ListEnvelope<T> = await apiGet<ListEnvelope<T>>(path, q, { timeoutMs: TIMEOUT_MS })
    items.push(...page.items)
    if (!asOf) asOf = page.as_of
    cursor = page.next
    if (!cursor) return { items, asOf }
  }
  console.error(`${path}: stopped after ${MAX_PAGES} pages, the list is incomplete`)
  return { items, asOf }
}

export function getSummary(): Promise<Envelope<Summary>> {
  return apiGet<Envelope<Summary>>('/summary', undefined, { timeoutMs: TIMEOUT_MS })
}

export function getManholes(): Promise<{ items: Manhole[]; asOf: string }> {
  return all<Manhole>('/manholes', {})
}

/** The newest `n` events, whatever their age (Overview). */
export async function getLatestEvents(n: number): Promise<FallEvent[]> {
  return (await apiGet<ListEnvelope<FallEvent>>('/fall-events', { limit: n }, { timeoutMs: TIMEOUT_MS })).items
}

/** Events overlapping the last `hours` hours, newest start first; optionally of one device. */
export async function getEventsSince(hours: number, deviceId?: string): Promise<FallEvent[]> {
  const params: Record<string, string | number> = { since: new Date(Date.now() - hours * 3_600_000).toISOString() }
  if (deviceId) params.device_id = deviceId
  return (await all<FallEvent>('/fall-events', params)).items
}

export async function getSeries(deviceId: string, days: 7 | 30): Promise<ManholeSeries> {
  const path = `/manholes/${encodeURIComponent(deviceId)}/series`
  return (await apiGet<Envelope<ManholeSeries>>(path, { days }, { timeoutMs: TIMEOUT_MS })).data
}

/** One key per event: the contract has no event id, (device, start) is unique (events of one device never overlap). */
export function eventKey(e: FallEvent): string {
  return `${e.device_id}|${e.started_at}`
}

/** GPS tracker with its last position (openapi Bundle). `online` = reported within 24 h. `moving` is carried by the contract but not shown: trip status is not computed (Spec #96). */
export interface Bundle {
  device_id: string
  name: string | null
  lat: number | null
  lon: number | null
  at: string | null
  moving: boolean | null
  online: boolean
}

/** One thinned track point (openapi TrackPoint). */
export interface TrackPoint {
  at: string
  lat: number
  lon: number
  speed_kmh: number | null
  moving: boolean | null
}

export function getBundles(): Promise<{ items: Bundle[]; asOf: string }> {
  return all<Bundle>('/bundles', {})
}

/** The thinned track of one tracker, oldest point first (the API sends newest first). */
export async function getTrack(deviceId: string, days = 7): Promise<TrackPoint[]> {
  const { items } = await all<TrackPoint>(`/bundles/${encodeURIComponent(deviceId)}/track`, { days })
  return items.reverse()
}
