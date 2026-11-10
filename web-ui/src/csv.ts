// CSV export of the Plan table, built in the browser (no write path on the server). RFC 4180 with a comma (EN) or semicolon (FR)
// separator, CRLF line ends; a field holding the separator, a double quote, CR or LF is wrapped in double quotes with inner quotes doubled. UTF-8 with a BOM so
// Excel opens accents correctly.
// CSV injection (OWASP "CSV Injection"): a text cell starting with = + - @ TAB or CR is prefixed with a single quote, so a
// spreadsheet never runs it as a formula. Numbers are written as numbers and never prefixed (a negative number stays a number).
// Europe/Paris like format.ts TZ; not imported from there so this module stays free of DOM-touching imports (vitest runs in node)
const TZ = 'Europe/Paris'

export type Cell = string | number | null
/** ',' (EN interface) or ';' (FR interface: French Excel splits on semicolons and reads ',' as the decimal mark), Spec v1.17. */
export type Sep = ',' | ';'

export const BOM = '\uFEFF'
const FORMULA_START = /^[=+\-@\t\r]/

/** One field. With ';' numbers use a decimal comma (that is why French Excel wants ';'); with ',' a decimal point. A field
 * holding the separator, a double quote, CR or LF is quoted with inner quotes doubled (RFC 4180, separator-aware). */
export function csvField(v: Cell, sep: Sep = ','): string {
  if (v === null) return ''
  if (typeof v === 'number') return Number.isFinite(v) ? (sep === ';' ? String(v).replace('.', ',') : String(v)) : ''
  const text = FORMULA_START.test(v) ? `'${v}` : v
  return /["\r\n]/.test(text) || text.includes(sep) ? `"${text.replace(/"/g, '""')}"` : text
}

/** Header plus rows, BOM first, CRLF after every record (the last one too, as RFC 4180 allows). */
export function toCsv(header: string[], rows: Cell[][], sep: Sep = ','): string {
  return BOM + [header, ...rows].map((r) => r.map((v) => csvField(v, sep)).join(sep) + '\r\n').join('')
}

/** "lutetia-plan-2026-11-10.csv": today in Europe/Paris, like every date on screen. */
export function csvFileName(now: Date = new Date()): string {
  const day = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  return `lutetia-plan-${day}.csv`
}

/** Hand the text to the browser as a file download. */
export function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.append(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
