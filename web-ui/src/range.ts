// Timeline ranges of the Manholes page (CMP-5), as written in the URL (?range=7d).
export type Range = '24h' | '7d' | '30d'
export const RANGES: readonly Range[] = ['24h', '7d', '30d']
export const RANGE_HOURS: Record<Range, number> = { '24h': 24, '7d': 168, '30d': 720 }

export function parseRange(v: unknown): Range {
  return typeof v === 'string' && (RANGES as readonly string[]).includes(v) ? (v as Range) : '24h'
}
