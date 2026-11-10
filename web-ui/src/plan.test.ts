// Chart sums of the Plan page (Task 10.2): only work orders with cable detail count, a missing weight is never 0. Synthetic rows.
import { describe, expect, it } from 'vitest'
import { hasCjk, hasWeight, round3, templateFor, tonnesByCableType, tonnesBySubcontractor, withMatchingTonnes } from './plan'
import type { Poi, PoiSegment } from './plan'
import { toCsv } from './csv'

function poi(no: string, sub: string | null, segs: number, tonnes: number | null): Poi {
  return {
    poi_no: no, uci: 'ZZ', subcontractor: sub, site_ville: null, commune_code: null, category: 'Transport', status_raw: null,
    occ_week_from: null, occ_week_to: null, occ_date_from: null, occ_date_to: null, received_date: null, planned_op_date: null,
    in_ledger: true, imported_at: '2026-11-08T04:12:00Z', segment_count: segs, total_length_km: null, planned_tonnes: tonnes,
  }
}
function seg(seq: number, type: string | null, w: number | null): PoiSegment {
  return { seq, cable_category: null, cable_type: type, infra: null, length_km: null, weight_t: w, ref_min_t: null, ref_avg_t: null, ref_max_t: null }
}

const rows = [poi('zz-1', 'zz A', 2, 1.5), poi('zz-2', 'zz A', 1, null), poi('zz-3', 'zz B', 0, null), poi('zz-4', null, 1, 2)]

describe('plan sums', () => {
  it('counts coverage like summary count - without_weight: at least one weighted segment', () => {
    expect(rows.filter(hasWeight).length).toBe(2) // zz-2 has a segment without weight: weight pending, not covered (review L-3)
  })
  it('sums tonnes per subcontractor, skipping weight pending instead of adding 0', () => {
    expect(tonnesBySubcontractor(rows)).toEqual([{ label: null, tonnes: 2 }, { label: 'zz A', tonnes: 1.5 }])
  })
  it('sums segment weights per cable type for the listed work orders only', () => {
    const segs = new Map([['zz-1', [seg(1, 'zz T1', 1), seg(2, 'zz T2', 0.5)]], ['zz-2', [seg(1, 'zz T1', null)]], ['zz-9', [seg(1, 'zz T1', 9)]]])
    expect(tonnesByCableType(rows, segs)).toEqual([{ label: 'zz T1', tonnes: 1 }, { label: 'zz T2', tonnes: 0.5 }])
  })
  it('under a cable type filter counts only the matching segments: TYPE-X unweighted + TYPE-Y 10 t, filter TYPE-X', () => {
    const one = [poi('zz-7', 'zz C', 2, 10)]
    const segs = new Map([['zz-7', [seg(1, 'TYPE-X', null), seg(2, 'TYPE-Y', 10)]]])
    const view = withMatchingTonnes(one, segs, { cable_type: 'TYPE-X' })
    expect(view[0].planned_tonnes).toBeNull() // weight pending, not 10 t
    expect(tonnesBySubcontractor(view)).toEqual([]) // the subcontractor chart does not count the 10 t of TYPE-Y
    expect(view.filter(hasWeight).length).toBe(0)
    expect(tonnesByCableType(view, segs, { cable_type: 'TYPE-X' })).toEqual([])
    const y = withMatchingTonnes(one, segs, { cable_type: 'TYPE-Y' })
    expect(tonnesBySubcontractor(y)).toEqual([{ label: 'zz C', tonnes: 10 }])
    expect(withMatchingTonnes(one, segs, {})[0].planned_tonnes).toBe(10) // no segment-level filter: whole work order
  })
  it('under a segment-level filter the segment count and total length are those of the matching segments too', () => {
    const one = [{ ...poi('zz-L', 'zz G', 3, 6), total_length_km: 10 }]
    const segs = new Map([['zz-L', [{ ...seg(1, 'X', 1), length_km: 2 }, { ...seg(2, 'X', 2), length_km: 3.5 }, { ...seg(3, 'Y', 3), length_km: 4.5 }]]])
    const v = withMatchingTonnes(one, segs, { cable_type: 'X' })[0]
    expect([v.segment_count, v.total_length_km, v.planned_tonnes]).toEqual([2, 5.5, 3])
    const whole = withMatchingTonnes(one, segs, {})[0]
    expect([whole.segment_count, whole.total_length_km]).toEqual([3, 10]) // no segment-level filter: the order as it is
  })
  it('filters on network (infra) the same way', () => {
    const one = [poi('zz-8', 'zz D', 2, 5)]
    const a = { ...seg(1, 'T', 2), infra: 'zz-aerial' }
    const b = { ...seg(2, 'T', 3), infra: 'zz-under' }
    expect(withMatchingTonnes(one, new Map([['zz-8', [a, b]]]), { network: 'zz-under' })[0].planned_tonnes).toBe(3)
  })
  it('drops an order where no single segment meets both cable type and network (X aerial + Y underground, filter X + underground)', () => {
    const a = [poi('zz-A', 'zz E', 2, 9)]
    const segs = new Map([['zz-A', [{ ...seg(1, 'X', 4), infra: 'aerial' }, { ...seg(2, 'Y', 5), infra: 'underground' }]]])
    expect(withMatchingTonnes(a, segs, { cable_type: 'X', network: 'underground' })).toEqual([]) // not shown, not weight pending
    expect(withMatchingTonnes(a, segs, { cable_type: 'X', network: 'aerial' })[0].planned_tonnes).toBe(4)
  })
  it('rounds summed tonnes: 0.1 + 0.2 exports as 0.3 (EN) and 0,3 (FR)', () => {
    const one = [poi('zz-9', 'zz F', 2, 0.3)]
    const segs = new Map([['zz-9', [seg(1, 'T', 0.1), seg(2, 'T', 0.2)]]])
    const v = withMatchingTonnes(one, segs, { cable_type: 'T' })
    expect(v[0].planned_tonnes).toBe(0.3)
    expect(tonnesByCableType(v, segs, { cable_type: 'T' })).toEqual([{ label: 'T', tonnes: 0.3 }])
    expect(toCsv(['t'], [[v[0].planned_tonnes]]).slice(1)).toBe('t\r\n0.3\r\n')
    expect(toCsv(['t'], [[v[0].planned_tonnes]], ';').slice(1)).toBe('t\r\n0,3\r\n')
    expect(round3(0.1 + 0.2)).toBe(0.3)
  })
  it('spots CJK text (an SLA step name in it is not shown)', () => {
    expect(hasCjk('POI issuing')).toBe(false)
    expect(hasCjk('Démontage')).toBe(false)
    expect(hasCjk('\u62c6\u9664')).toBe(true)
    expect(hasCjk('\u30c6\u30b9\u30c8')).toBe(true)
    expect(hasCjk('\ud14c\uc2a4\ud2b8')).toBe(true)
  })
  it('maps work-order categories to SLA templates; anything else has none', () => {
    expect(templateFor('Transport')).toBe('Transportation')
    expect(templateFor(' distribution ')).toBe('Distribution')
    expect(templateFor('Other')).toBeNull()
    expect(templateFor(undefined)).toBeNull()
  })
})
