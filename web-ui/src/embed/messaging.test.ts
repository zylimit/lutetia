// risk: high
// THR-3: the widget sends only to, and accepts only from, the origins of /api/v1/embed-config; messages carry device and time only.
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FallEvent } from '../resources'
import { acceptHostMessage, fallEventSelected, hostOrigin, originMatches, postToHost, resize, throttleHeights } from './messaging'
import type { FrameHint } from './messaging'

const WILD = 'https://*.digifiber.net'
const LIST = ['https://ofr.digifiber.net', WILD]
const EVENT: FallEvent = { device_id: 'dev-1', started_at: '2026-11-08T01:14:07Z', ended_at: null, flips: 9, duration_sec: null }

/** Only a referrer (Firefox: no location.ancestorOrigins). */
function ref(referrer: string): FrameHint {
  return { ancestor: null, referrer }
}

function sink() {
  const calls: { msg: unknown; origin: string }[] = []
  return { calls, postMessage: (msg: unknown, origin: string) => void calls.push({ msg, origin }) }
}

describe('originMatches (same rule as callers.py origin_allowed)', () => {
  it('the wildcard takes one or more labels under digifiber.net', () => {
    expect(originMatches('https://ofr.digifiber.net', WILD)).toBe(true)
    expect(originMatches('https://test-host.digifiber.net', WILD)).toBe(true)
    expect(originMatches('https://a.b.digifiber.net', WILD)).toBe(true)
  })
  it.each([
    'https://evil-digifiber.net',
    'https://digifiber.net.evil.com',
    'http://x.digifiber.net',
    'https://digifiber.net',
    'https://x.digifiber.net:8443',
    'https://x.digifiber.net/',
    'https://X.digifiber.net',
    'https://-x.digifiber.net',
    'https://x..digifiber.net',
    'https://.digifiber.net',
    'https://evil.example',
    'null',
    '',
  ])('refuses %s', (origin) => {
    expect(originMatches(origin, WILD)).toBe(false)
  })
  it('an exact entry matches itself only', () => {
    expect(originMatches('https://ofr.digifiber.net', 'https://ofr.digifiber.net')).toBe(true)
    expect(originMatches('https://ofr2.digifiber.net', 'https://ofr.digifiber.net')).toBe(false)
  })
  it('a malformed pattern matches nothing', () => {
    expect(originMatches('https://x.digifiber.net', '*')).toBe(false)
    expect(originMatches('https://x.digifiber.net', 'https://*')).toBe(false)
    expect(originMatches('https://x.digifiber.net', "'none'")).toBe(false)
  })
})

describe('sending', () => {
  it('goes to the referrer origin when it is allowed', () => {
    const t = sink()
    expect(postToHost(t, ref('https://ofr.digifiber.net/sites/42?tab=map'), LIST, fallEventSelected(EVENT, '864317087590107'))).toBe(true)
    expect(t.calls).toEqual([
      {
        msg: { type: 'lutetia:fall-event-selected', v: 1, device_id: 'dev-1', imei: '864317087590107', started_at: '2026-11-08T01:14:07Z' },
        origin: 'https://ofr.digifiber.net',
      },
    ])
  })
  it.each(['https://evil.example/page', 'https://evil-digifiber.net/', 'http://ofr.digifiber.net/', '', 'not a url'])(
    'is not sent when the framing page is %s',
    (referrer) => {
      const t = sink()
      expect(postToHost(t, ref(referrer), LIST, resize(120))).toBe(false)
      expect(t.calls).toEqual([])
    },
  )
  it('is not sent before the list is loaded, nor without a parent window', () => {
    const t = sink()
    expect(postToHost(t, ref('https://ofr.digifiber.net/'), [], resize(120))).toBe(false)
    expect(postToHost(null, ref('https://ofr.digifiber.net/'), LIST, resize(120))).toBe(false)
    expect(t.calls).toEqual([])
  })
  it('the event message carries no position', () => {
    const keys = Object.keys(fallEventSelected(EVENT, 'x')).sort()
    expect(keys).toEqual(['device_id', 'imei', 'started_at', 'type', 'v'])
  })
  it('hostOrigin keeps only the origin of the referrer', () => {
    expect(hostOrigin(ref('https://ofr.digifiber.net/a/b?c=1#d'), LIST)).toBe('https://ofr.digifiber.net')
  })
  it('the parent origin (ancestorOrigins) is used when allowed', () => {
    const t = sink()
    expect(postToHost(t, { ancestor: 'https://x.digifiber.net', referrer: 'https://x.digifiber.net/p' }, LIST, resize(50))).toBe(true)
    expect(t.calls[0].origin).toBe('https://x.digifiber.net')
  })
  it('an empty referrer (no-referrer policy) does not matter when the parent origin is known', () => {
    const t = sink()
    expect(postToHost(t, { ancestor: 'https://ofr.digifiber.net', referrer: '' }, LIST, resize(50))).toBe(true)
    expect(t.calls).toEqual([{ msg: { type: 'lutetia:resize', v: 1, height: 50 }, origin: 'https://ofr.digifiber.net' }])
  })
  it('neither parent origin nor referrer: not sent', () => {
    const t = sink()
    expect(postToHost(t, { ancestor: null, referrer: '' }, LIST, resize(50))).toBe(false)
    expect(t.calls).toEqual([])
  })
  it('a refused parent origin is not overridden by an allowed referrer', () => {
    const t = sink()
    expect(postToHost(t, { ancestor: 'https://evil.example', referrer: 'https://ofr.digifiber.net/' }, LIST, resize(50))).toBe(false)
    expect(t.calls).toEqual([])
  })
})

describe('receiving', () => {
  it('drops a message from an origin not on the list, whatever it says', () => {
    for (const origin of ['https://evil.example', 'https://digifiber.net.evil.com', 'http://ofr.digifiber.net', 'null']) {
      expect(acceptHostMessage({ origin, data: { type: 'lutetia:fall-event-selected', v: 1 } }, LIST)).toBeNull()
    }
  })
  it('drops everything while the list is empty', () => {
    expect(acceptHostMessage({ origin: 'https://ofr.digifiber.net', data: { type: 'lutetia:x', v: 1 } }, [])).toBeNull()
  })
  it('drops a message without the lutetia envelope even from an allowed origin', () => {
    for (const data of [null, 'lutetia:x', { type: 'other', v: 1 }, { type: 'lutetia:x' }, { type: 'lutetia:x', v: '1' }]) {
      expect(acceptHostMessage({ origin: 'https://ofr.digifiber.net', data }, LIST)).toBeNull()
    }
  })
  it('accepts an enveloped message from an allowed origin', () => {
    expect(acceptHostMessage({ origin: 'https://x.digifiber.net', data: { type: 'lutetia:ping', v: 1 } }, LIST)?.type).toBe('lutetia:ping')
  })
})

describe('throttleHeights', () => {
  afterEach(() => void vi.useRealTimers())
  it('sends the latest height once per window, and nothing when it did not change', () => {
    vi.useFakeTimers()
    const sent: number[] = []
    const h = throttleHeights((x) => sent.push(x), 150)
    h.push(100.2)
    h.push(180)
    h.push(240.4)
    vi.advanceTimersByTime(150)
    expect(sent).toEqual([241])
    h.push(240.1)
    vi.advanceTimersByTime(150)
    expect(sent).toEqual([241])
    h.push(300)
    h.stop()
    vi.advanceTimersByTime(300)
    expect(sent).toEqual([241])
  })
})
