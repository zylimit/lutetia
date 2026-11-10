// Dates, durations and numbers in the interface language; every time is shown in Europe/Paris with its abbreviation
// (Design-Brief 6.1, CMP-4: "Sun 8 Nov, 02:14:07 CET" / "dim. 8 nov., 02:14:07 CET").
import { i18n, t } from './i18n'

export const TZ = 'Europe/Paris'

function locale(): string {
  return i18n.lang === 'fr' ? 'fr-FR' : 'en-GB'
}

/** CET or CEST for that instant. Taken from the English formatter in both languages: French ICU would say "UTC+1". */
export function tzAbbr(d: Date): string {
  const part = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, timeZoneName: 'short' }).formatToParts(d).find((p) => p.type === 'timeZoneName')
  return part?.value ?? TZ
}

/** "Sun 8 Nov, 02:14:07 CET" (seconds optional). */
export function dateTime(iso: string, seconds = false): string {
  const d = new Date(iso)
  const text = new Intl.DateTimeFormat(locale(), {
    timeZone: TZ,
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    ...(seconds ? { second: '2-digit' } : {}),
  }).format(d)
  return `${text} ${tzAbbr(d)}`
}

/** "8 Nov, 02:00" — chart axis ticks, in Europe/Paris like the tooltip (no abbreviation: it would repeat on every tick). */
export function axisStamp(ms: number): string {
  return new Intl.DateTimeFormat(locale(), { timeZone: TZ, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(ms))
}

/** "08:42 CET" — the "as of" stamps. */
export function clock(iso: string): string {
  const d = new Date(iso)
  return `${new Intl.DateTimeFormat(locale(), { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(d)} ${tzAbbr(d)}`
}

/** "6 min", "2 h 05 min"; under a minute counts as 1 min (an event lasts at least one reading). */
export function duration(sec: number): string {
  const minutes = Math.max(1, Math.round(sec / 60))
  if (minutes < 120) return `${minutes} ${t('min')}`
  return `${Math.floor(minutes / 60)} ${t('hour')} ${String(minutes % 60).padStart(2, '0')} ${t('min')}`
}

export function num(n: number, digits = 1): string {
  return new Intl.NumberFormat(locale(), { maximumFractionDigits: digits }).format(n)
}
