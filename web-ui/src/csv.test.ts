// CSV export escaping (Task 10.2): what is written must read back as the original value, except the CSV-injection guard, which
// on purpose adds a leading single quote to text starting with = + - @ TAB or CR. Synthetic names only.
import { describe, expect, it } from 'vitest'
import { BOM, csvField, csvFileName, toCsv } from './csv'
import type { Cell } from './csv'

/** A strict RFC 4180 reader (comma, CRLF or LF records, quoted fields with doubled quotes), only for the round trip. */
function parseCsv(text: string, sep = ','): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"'
        i++
      } else if (c === '"') quoted = false
      else field += c
    } else if (c === '"') quoted = true
    else if (c === sep) {
      row.push(field)
      field = ''
    } else if (c === '\r' && text[i + 1] === '\n') {
      continue
    } else if (c === '\n') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else field += c
  }
  if (field || row.length) rows.push([...row, field])
  return rows
}

const PLAIN = ['zz Sub A', 'zz Sub, Comma', 'zz "Quoted" Sub', 'zz Line\nBreak', 'zz CR\r\nLF', 'zz, "all", of\nthem', 'zz é à ç']
const RISKY = ['=1+1', '+33 zz', '-zz minus', '@SUM(A1)', '\tzz tab', '\rzz cr']

describe('csv export', () => {
  it('starts with a UTF-8 BOM and ends every record with CRLF', () => {
    const text = toCsv(['a', 'b'], [['x', 1]])
    expect(text.startsWith(BOM)).toBe(true)
    expect(text.slice(1)).toBe('a,b\r\nx,1\r\n')
  })

  it('round-trips commas, double quotes and line breaks to the original value', () => {
    const rows: Cell[][] = PLAIN.map((s) => [s, 2.5])
    const back = parseCsv(toCsv(['subcontractor', 'tonnes'], rows).slice(1))
    expect(back[0]).toEqual(['subcontractor', 'tonnes'])
    expect(back.slice(1).map((r) => r[0])).toEqual(PLAIN)
    expect(back.slice(1).every((r) => r[1] === '2.5')).toBe(true)
  })

  it('prefixes text starting with = + - @ TAB CR with a single quote (expected: the quote, then the original)', () => {
    const back = parseCsv(toCsv(['subcontractor'], RISKY.map((s) => [s])).slice(1))
    expect(back.slice(1).map((r) => r[0])).toEqual(RISKY.map((s) => `'${s}`))
  })

  it('leaves numbers, including negative ones, unquoted and unprefixed; null is an empty field', () => {
    expect(csvField(-1.5)).toBe('-1.5')
    expect(csvField(0)).toBe('0')
    expect(csvField(null)).toBe('')
    expect(csvField('weight pending')).toBe('weight pending')
  })

  it('FR: semicolon separator, decimal comma, fields with ; quoted, and the round trip still gives the original', () => {
    const text = toCsv(['subcontractor', 'tonnes'], [['zz Sub; Semi', 2.5], ['zz, comma only', -1], ['=1;2', null]], ';')
    expect(text.startsWith(BOM)).toBe(true)
    expect(text.slice(1).split('\r\n')[1]).toBe('"zz Sub; Semi";2,5')
    expect(text.slice(1).split('\r\n')[2]).toBe('zz, comma only;-1') // a comma needs no quotes when the separator is ;
    const back = parseCsv(text.slice(1), ';')
    expect(back.slice(1).map((r) => r[0])).toEqual(['zz Sub; Semi', 'zz, comma only', "'=1;2"])
  })

  it('names the file with the Paris date', () => {
    expect(csvFileName(new Date('2026-11-10T23:30:00Z'))).toBe('lutetia-plan-2026-11-11.csv') // 00:30 in Paris
    expect(csvFileName(new Date('2026-07-01T10:00:00Z'))).toBe('lutetia-plan-2026-07-01.csv')
  })
})
