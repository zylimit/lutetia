// Plan page data (SCREEN-4): POI work orders, their cable segments and the SLA templates, with field names exactly those of
// lutetia/web/openapi.json, plus the pure sums behind the two charts. Excel snapshot: Ariane is the source of truth (Spec v1.12).
import { all } from './resources'

export interface Poi {
  poi_no: string
  uci: string | null
  subcontractor: string | null
  site_ville: string | null
  commune_code: string | null
  category: string | null
  status_raw: string | null // OCC text as written in the ledger
  occ_week_from: number | null
  occ_week_to: number | null
  occ_date_from: string | null
  occ_date_to: string | null
  received_date: string | null
  planned_op_date: string | null
  in_ledger: boolean
  imported_at: string
  segment_count: number
  total_length_km: number | null
  planned_tonnes: number | null // null = weight pending, never 0
}

export interface PoiSegment {
  seq: number
  cable_category: string | null
  cable_type: string | null
  infra: string | null // underground / aerial, the `network` filter
  length_km: number | null
  weight_t: number | null
  ref_min_t: number | null
  ref_avg_t: number | null
  ref_max_t: number | null
}

export type SlaUnit = 'minute' | 'hour' | 'day' | 'workday' | 'week' | 'month' | 'tonne_per_day'

export interface SlaStep {
  seq: number
  step: string
  owner: 'customer' | 'huawei' | 'partner' | string
  sla_text: string | null // never shown: written in Chinese (Decisions 2026-11-10); only tells "unparsed" from "none given"
  sla_value: number | null
  sla_value_min: number | null
  sla_unit: SlaUnit | string | null
  sla_scope: 'access' | 'aggregation' | 'backbone' | 'other' | string | null
}

export interface SlaTemplate {
  template: string
  steps: SlaStep[]
}

/** The six filters of /api/v1/pois, in screen order; each is also a URL query key. */
export const FILTER_KEYS = ['uci', 'subcontractor', 'commune', 'category', 'network', 'cable_type'] as const
export type FilterKey = (typeof FILTER_KEYS)[number]
export type Filters = Partial<Record<FilterKey, string>>

/** No Ariane address for a work order was given (Spec names the host only, no plan-board URL): without it the link is not shown. */
export const ARIANE_PLAN_URL: string | null = null

export interface Listed<T> {
  items: T[]
  asOf: string | null
  source: string
}

export async function getPois(filters: Filters): Promise<Listed<Poi>> {
  const params: Record<string, string> = {}
  for (const k of FILTER_KEYS) if (filters[k]) params[k] = filters[k] as string
  const r = await all<Poi>('/pois', params)
  return { items: r.items, asOf: r.asOf || null, source: 'excel-snapshot' }
}

export async function getSegments(poiNo: string): Promise<PoiSegment[]> {
  return (await all<PoiSegment>(`/pois/${encodeURIComponent(poiNo)}/segments`, {})).items
}

export async function getSlaTemplates(): Promise<Listed<SlaTemplate>> {
  const r = await all<SlaTemplate>('/sla-templates', {})
  return { items: r.items, asOf: r.asOf || null, source: 'excel-snapshot' }
}

/** Segments of many work orders, a few requests at a time. A failed one rejects the whole call (the chart says so). */
export async function getSegmentsOf(poiNos: string[], parallel = 4): Promise<Map<string, PoiSegment[]>> {
  const out = new Map<string, PoiSegment[]>()
  const queue = [...poiNos]
  async function worker(): Promise<void> {
    for (let id = queue.shift(); id !== undefined; id = queue.shift()) out.set(id, await getSegments(id))
  }
  await Promise.all(Array.from({ length: Math.min(parallel, queue.length) }, worker))
  return out
}

/** Covered by the charts = has a planned weight (at least one segment carries one): the same rule as /api/v1/summary,
 * where that count is pois.count - pois.without_weight (Task 10.2 review L-3). */
export function hasWeight(p: Poi): boolean {
  return p.planned_tonnes !== null
}

/** cable_type and network filter segments, not work orders: tonnes then come from the matching segments only (Spec v1.17). */
export function segmentFiltered(f: Filters): boolean {
  return !!(f.cable_type || f.network)
}

export function segmentMatches(s: PoiSegment, f: Filters): boolean {
  return (!f.cable_type || s.cable_type === f.cable_type) && (!f.network || s.infra === f.network)
}

/** Under a segment-level filter, each row's planned_tonnes is the sum of its matching segments that carry a weight; none of them
 * weighted -> null (weight pending). Without such a filter the rows are returned as they are (whole work order). */
export function withMatchingTonnes(rows: Poi[], segments: Map<string, PoiSegment[]>, f: Filters): Poi[] {
  if (!segmentFiltered(f)) return rows
  return rows.flatMap((p) => {
    const matching = (segments.get(p.poi_no) ?? []).filter((s) => segmentMatches(s, f))
    // the API checks cable_type and network with two separate EXISTS: an order with X aerial + Y underground passes "X + underground"
    // although no single segment is both; such an order is dropped here, not shown as weight pending (review N-2)
    if (f.cable_type && f.network && !matching.length) return []
    const weights = matching.filter((s) => s.weight_t !== null).map((s) => s.weight_t as number)
    return [{ ...p, planned_tonnes: weights.length ? round3(weights.reduce((a, b) => a + b, 0)) : null }]
  })
}

/** Sums of tonnes rounded to the kg, so 0.1 + 0.2 shows and exports as 0.3, not 0.30000000000000004 (review N-1). */
export function round3(x: number): number {
  return Math.round(x * 1000) / 1000
}

export interface Bar {
  label: string | null // null = the ledger cell is empty
  tonnes: number
}

function sorted(map: Map<string | null, number>): Bar[] {
  return [...map.entries()].map(([label, tonnes]) => ({ label, tonnes: round3(tonnes) })).sort((a, b) => b.tonnes - a.tonnes)
}

/** Planned tonnes per subcontractor; weight pending adds nothing (never 0). Give it the rows of withMatchingTonnes. */
export function tonnesBySubcontractor(rows: Poi[]): Bar[] {
  const m = new Map<string | null, number>()
  for (const p of rows) if (p.planned_tonnes !== null) m.set(p.subcontractor, (m.get(p.subcontractor) ?? 0) + p.planned_tonnes)
  return sorted(m)
}

/** Planned tonnes per cable type over the listed work orders' segments (only the matching ones under a segment-level filter). */
export function tonnesByCableType(rows: Poi[], segments: Map<string, PoiSegment[]>, f: Filters = {}): Bar[] {
  const m = new Map<string | null, number>()
  for (const p of rows) {
    for (const s of segments.get(p.poi_no) ?? []) {
      if (s.weight_t !== null && segmentMatches(s, f)) m.set(s.cable_type, (m.get(s.cable_type) ?? 0) + s.weight_t)
    }
  }
  return sorted(m)
}

/** Chinese, Japanese or Korean script: such text is never shown (the interface is English / French only). */
export function hasCjk(text: string): boolean {
  return /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]/.test(text)
}

/** Work-order category -> SLA template (DEV-PLAN Task 10.3); MASSIVE has no category and is listed in the reference only. */
export function templateFor(category: string | null | undefined): string | null {
  const c = (category ?? '').trim().toLowerCase()
  if (c.startsWith('transport')) return 'Transportation'
  if (c.startsWith('distribution')) return 'Distribution'
  return null
}

/** Distinct non-empty values, sorted, for a filter's options. */
export function distinct(values: (string | null)[]): string[] {
  return [...new Set(values.filter((v): v is string => !!v))].sort((a, b) => a.localeCompare(b))
}
