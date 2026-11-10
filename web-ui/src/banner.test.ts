// risk: medium
import { describe, expect, it } from 'vitest'
import { offlineAsOf, pickBanner, sameParisDay } from './banner'

describe('sameParisDay (offline banner: time only for today, with the date otherwise)', () => {
  it('same Paris day', () => {
    expect(sameParisDay(new Date('2026-11-10T08:00:00Z'), new Date('2026-11-10T20:00:00Z'))).toBe(true)
  })
  it('judged in Europe/Paris, not UTC: 23:30 and 00:30 CET are two days (22:30Z and 23:30Z, both 10 Nov in UTC)', () => {
    expect(sameParisDay(new Date('2026-11-10T22:30:00Z'), new Date('2026-11-10T23:30:00Z'))).toBe(false)
  })
  it('an import from days ago is another day', () => {
    expect(sameParisDay(new Date('2026-11-08T14:05:00Z'), new Date('2026-11-11T09:00:00Z'))).toBe(false)
  })
})

describe('offlineAsOf', () => {
  it('the page resource time wins (Bundles / Plan)', () => {
    expect(offlineAsOf('2026-11-10T07:42:00Z', '2026-11-10T08:10:00Z')).toBe('2026-11-10T07:42:00Z')
  })
  it('falls back to the summary time (Overview / Manholes), or nothing', () => {
    expect(offlineAsOf(null, '2026-11-10T08:10:00Z')).toBe('2026-11-10T08:10:00Z')
    expect(offlineAsOf(null, null)).toBeNull()
  })
})

describe('pickBanner', () => {
  it('offline wins over a stale flag from the saved summary and over a failed refresh', () => {
    expect(pickBanner({ offline: true, stale: true, error: false })).toBe('offline')
    expect(pickBanner({ offline: true, stale: false, error: true })).toBe('offline')
    expect(pickBanner({ offline: true, stale: true, error: true })).toBe('offline')
  })
  it('online: error before data delayed', () => {
    expect(pickBanner({ offline: false, stale: true, error: true })).toBe('error')
    expect(pickBanner({ offline: false, stale: true, error: false })).toBe('stale')
  })
  it('online and fresh: no banner', () => {
    expect(pickBanner({ offline: false, stale: false, error: false })).toBeNull()
  })
})
