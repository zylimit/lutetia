// Runtime side of messaging.ts: the allowed origins from /api/v1/embed-config, sending to the parent window, the message
// listener and the height reports. Nothing is sent before the origin list is loaded.
import { apiGet } from '../api'
import type { Envelope } from '../api'
import { TIMEOUT_MS } from '../resources'
import { acceptHostMessage, postToHost, resize, throttleHeights } from './messaging'
import type { FrameHint, OutMessage } from './messaging'

const RESIZE_THROTTLE_MS = 150

let patterns: readonly string[] = []
let loading: Promise<void> | null = null
let observed: HTMLElement | null = null // the element whose height is reported (startHostLink)

/** Loads the origin list once; a failure is logged and retried on the next call (each 60 s refresh asks again). */
export function loadEmbedConfig(): Promise<void> {
  if (patterns.length) return Promise.resolve()
  if (!loading) {
    loading = apiGet<Envelope<{ origins: string[] }>>('/embed-config', undefined, { redirectOn401: false, timeoutMs: TIMEOUT_MS })
      .then((r) => {
        patterns = r.data.origins.filter((o) => typeof o === 'string')
        // Heights observed before the list arrived were not sent: report the current one now, whichever load succeeds first.
        if (observed) reportHeight(observed)
      })
      .catch((e: unknown) => {
        console.error('embed: could not load the allowed host origins, no message is sent until they load', e)
      })
      .finally(() => {
        loading = null
      })
  }
  return loading
}

function parentWindow(): Window | null {
  return window.parent !== window ? window.parent : null
}

/** True when the message went out; false (and a console note) when the host is unknown or not on the list. */
function frameHint(): FrameHint {
  const ancestors = window.location.ancestorOrigins // Chromium / Safari only; Firefox has none
  return { ancestor: ancestors && ancestors.length ? ancestors[0] : null, referrer: document.referrer }
}

export function sendToHost(msg: OutMessage): boolean {
  const sent = postToHost(parentWindow(), frameHint(), patterns, msg)
  if (!sent && parentWindow() !== null) console.warn(`embed: ${msg.type} not sent, the framing page is not an allowed origin (or the list is not loaded)`)
  return sent
}

/** Host-to-widget messages: v1 defines none, so an accepted one is only acknowledged in the console; others are dropped. */
function onMessage(ev: MessageEvent): void {
  const msg = acceptHostMessage(ev, patterns)
  if (msg) console.info(`embed: message ${msg.type} v${msg.v} from the host has no handler in v1`)
}

/** Starts the listener and the height reports of `el`; returns the stop function. */
export function startHostLink(el: HTMLElement): () => void {
  window.addEventListener('message', onMessage)
  observed = el
  const heights = throttleHeights((h) => sendToHost(resize(h)), RESIZE_THROTTLE_MS)
  const ro = new ResizeObserver(() => heights.push(el.getBoundingClientRect().height))
  ro.observe(el)
  return () => {
    window.removeEventListener('message', onMessage)
    observed = null
    ro.disconnect()
    heights.stop()
  }
}

/** Once the list arrives, report the current height (the first ResizeObserver call may have come before it). */
export function reportHeight(el: HTMLElement): void {
  if (patterns.length) sendToHost(resize(el.getBoundingClientRect().height))
}
