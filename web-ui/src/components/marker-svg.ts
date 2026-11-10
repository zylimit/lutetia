// Marker glyphs for ManholeMap (Leaflet divIcon html). Class names only, no style attributes (strict CSP), colours from CSS.
import type { Manhole } from '../resources'

export type MarkerKind = 'quiet' | 'moved' | 'moving' | 'offline' | 'suspicious' | 'inactive'

/** One marker kind per manhole: the API status, with offline + open_event drawn apart (Decisions 2026-11-10). Unknown statuses fall back to quiet's shape. */
export function markerKind(m: Pick<Manhole, 'status' | 'open_event'>): MarkerKind {
  if (m.status === 'offline') return m.open_event ? 'suspicious' : 'offline'
  if (m.status === 'moved' || m.status === 'moving' || m.status === 'inactive') return m.status
  return 'quiet'
}

const SHAPES: Record<MarkerKind, string> = {
  quiet: '<circle class="shape" cx="16" cy="16" r="9"/>',
  moved: '<path class="shape" d="M16 3 29 27H3Z"/>',
  moving: '<path class="shape" d="M16 3 29 27H3Z"/>',
  offline: '<circle class="shape" cx="16" cy="16" r="9"/><path class="slash" d="m9 23 14-14"/>',
  suspicious: '<circle class="shape" cx="16" cy="16" r="9"/><path class="slash" d="m9 23 14-14"/><path class="alert" d="M25 19 32 31H18Z"/>',
  inactive: '<circle class="shape" cx="16" cy="16" r="4"/>',
}

export function markerSvg(kind: MarkerKind, unverified: boolean): string {
  const corner = unverified ? '<rect class="unverified" x="25" y="1" width="6" height="6"/>' : ''
  return `<svg viewBox="0 0 32 32" width="32" height="32" aria-hidden="true" focusable="false">${SHAPES[kind]}${corner}</svg>`
}
