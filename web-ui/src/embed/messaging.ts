// postMessage between an embedded widget and its host page (Phase 12, THR-3, Architecture-Design ADR-6).
// Pure functions, no DOM at import time (vitest runs them in Node). host.ts wires them to the real window.
// Origin rule = lutetia/web/callers.py origin_allowed: https only, no port / path, lowercase labels [a-z0-9-] not starting or
// ending in '-'. A pattern https://*.<suffix> matches one or more labels before .<suffix>, never the bare <suffix> itself.
import type { FallEvent } from '../resources'

export const MESSAGE_VERSION = 1
export const PREFIX = 'lutetia:'
const LABEL = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/
const WILDCARD = 'https://*.'

export interface FallEventSelected {
  type: 'lutetia:fall-event-selected'
  v: 1
  device_id: string // internal id, the key of /api/v1 (?device_id=)
  imei: string // what the widget shows; equals device_id when the manhole has no name
  started_at: string
}

export interface Resize {
  type: 'lutetia:resize'
  v: 1
  height: number
}

export type OutMessage = FallEventSelected | Resize

/** A message from the host that passed the origin and envelope checks. v1 defines no host-to-widget types yet. */
export interface HostMessage {
  type: string
  v: number
  data: Record<string, unknown>
}

function labelsOk(host: string): boolean {
  return host.length > 0 && host.split('.').every((l) => LABEL.test(l))
}

/** origin is exactly "https://<host>" with a well-formed lowercase host, nothing else. */
function cleanHost(origin: string): string | null {
  if (!origin.startsWith('https://')) return null
  const host = origin.slice('https://'.length)
  return labelsOk(host) ? host : null
}

export function originMatches(origin: string, pattern: string): boolean {
  const host = cleanHost(origin)
  if (host === null) return false
  if (pattern.startsWith(WILDCARD)) {
    const suffix = pattern.slice(WILDCARD.length)
    if (!labelsOk(suffix) || !host.endsWith('.' + suffix)) return false
    return labelsOk(host.slice(0, -(suffix.length + 1)))
  }
  return cleanHost(pattern) !== null && origin === pattern
}

export function originAllowed(origin: unknown, patterns: readonly string[]): boolean {
  return typeof origin === 'string' && patterns.some((p) => originMatches(origin, p))
}

/** Where the framing page says it is: location.ancestorOrigins[0] (the parent's origin, Chromium / Safari) and
 * document.referrer (the page that loaded the frame; empty under a no-referrer policy). */
export interface FrameHint {
  ancestor: string | null
  referrer: string
}

function referrerOrigin(referrer: string): string | null {
  if (!referrer) return null
  try {
    return new URL(referrer).origin
  } catch {
    return null // not a URL: no host to answer
  }
}

/** The origin of the page that framed the widget: the parent's origin when the browser gives it, else the referrer's; null
 * when neither is known or the one taken is not on the list (the referrer is not a fallback for a refused parent origin). */
export function hostOrigin(hint: FrameHint, patterns: readonly string[]): string | null {
  const origin = hint.ancestor || referrerOrigin(hint.referrer)
  return origin !== null && originAllowed(origin, patterns) ? origin : null
}

export interface Target {
  postMessage(message: unknown, targetOrigin: string): void
}

/** Sends only to an allowed host origin (the browser then delivers only if the parent really is that origin). */
export function postToHost(target: Target | null, hint: FrameHint, patterns: readonly string[], msg: OutMessage): boolean {
  const origin = hostOrigin(hint, patterns)
  if (target === null || origin === null) return false
  target.postMessage(msg, origin)
  return true
}

/** Checks a received message: origin on the list first, then the {type: "lutetia:…", v} envelope. Anything else -> null. */
export function acceptHostMessage(ev: { origin: string; data: unknown }, patterns: readonly string[]): HostMessage | null {
  if (!originAllowed(ev.origin, patterns)) return null
  const d = ev.data
  if (typeof d !== 'object' || d === null) return null
  const rec = d as Record<string, unknown>
  if (typeof rec.type !== 'string' || !rec.type.startsWith(PREFIX) || typeof rec.v !== 'number') return null
  return { type: rec.type, v: rec.v, data: rec }
}

/** Device and time only, never a position (THR-3). */
export function fallEventSelected(e: FallEvent, imei: string): FallEventSelected {
  return { type: 'lutetia:fall-event-selected', v: MESSAGE_VERSION, device_id: e.device_id, imei, started_at: e.started_at }
}

export function resize(height: number): Resize {
  return { type: 'lutetia:resize', v: MESSAGE_VERSION, height: Math.ceil(height) }
}

/** Calls send(height) at most once per `ms`, always with the latest height, and only when it changed. */
export function throttleHeights(send: (height: number) => void, ms: number): { push(height: number): void; stop(): void } {
  let last = -1
  let pending: number | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  const flush = () => {
    timer = null
    if (pending !== null && pending !== last) {
      last = pending
      send(pending)
    }
    pending = null
  }
  return {
    push(height: number): void {
      pending = Math.ceil(height)
      if (timer === null) timer = setTimeout(flush, ms)
    },
    stop(): void {
      if (timer !== null) clearTimeout(timer)
      timer = null
    },
  }
}
