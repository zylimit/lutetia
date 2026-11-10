#!/usr/bin/env node
// Task 10.2 walk-through of the Plan page, for the tester to run on fra / the local compose stack with the Playwright in ~/tools/pw:
//   BASE_URL=https://… WALK_USER=… WALK_PASSWORD=… node walk-plan.cjs
// Nothing real is written here: base URL, account and password come only from the environment. Read-only (GETs only; the CSV is
// built in the browser and lands in Playwright's temporary download folder, removed when the browser closes).
// Steps: sign in -> Plan -> the source note is there -> pick the first subcontractor -> URL carries it -> table rows = CSV data rows
// (Playwright download, RFC 4180 parse, BOM present) -> Clear filters -> expand a work order with segments: aria-expanded=true and
// the segment table appears -> the SLA reference is there (steps or the not-imported-yet empty state) -> console errors 0, CSP 0.
// Exit 0 = every step passed, 1 = a step failed (the failing step is printed), 2 = missing environment or Playwright.
'use strict'

const fs = require('node:fs')

let chromium
try {
  ;({ chromium } = require('playwright'))
} catch (e) {
  console.error('walk-plan: Playwright not found (run from ~/tools/pw):', e.message)
  process.exit(2)
}

const BASE = (process.env.BASE_URL || '').replace(/\/+$/, '')
const USER = process.env.WALK_USER || ''
const PASSWORD = process.env.WALK_PASSWORD || ''
const WIDTH = Number(process.env.WALK_WIDTH || 1440)
if (!BASE || !USER || !PASSWORD) {
  console.error('walk-plan: set BASE_URL, WALK_USER and WALK_PASSWORD')
  process.exit(2)
}

function step(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
  if (!ok) throw new Error(`step failed: ${name}`)
}

/** RFC 4180 records (quoted fields may hold commas and line breaks). */
function csvRecords(text) {
  const rows = []
  let row = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') (field += '"'), i++
      else if (c === '"') quoted = false
      else field += c
    } else if (c === '"') quoted = true
    else if (c === ',') row.push(field), (field = '')
    else if (c === '\r') continue
    else if (c === '\n') row.push(field), rows.push(row), (row = []), (field = '')
    else field += c
  }
  if (field || row.length) rows.push([...row, field])
  return rows
}

async function main() {
  const browser = await chromium.launch()
  const consoleErrors = []
  try {
    const ctx = await browser.newContext({ viewport: { width: WIDTH, height: 900 }, locale: 'en-GB', acceptDownloads: true })
    const page = await ctx.newPage()
    page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
    page.on('pageerror', (e) => consoleErrors.push(String(e)))
    await page.addInitScript(() => {
      window.__csp = []
      document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`))
    })
    await page.goto(`${BASE}/app/signin?next=${encodeURIComponent('/app/plan')}`)
    await page.fill('input[name="username"]', USER)
    await page.fill('input[name="password"]', PASSWORD)
    await Promise.all([page.waitForURL((u) => !u.pathname.startsWith('/app/signin')), page.click('form button[type="submit"]')])
    await page.goto(`${BASE}/app/plan`)

    const note = page.locator('[data-testid="source-note"]')
    await page.locator('[data-testid="plan-table"]').waitFor({ timeout: 20000 })
    step('source note says Excel snapshot and Ariane', /Excel snapshot, as of .+(CET|CEST) · Ariane is the source of truth/.test((await note.textContent()) || ''), (await note.textContent())?.trim())
    const coverage = ((await page.locator('[data-testid="chart-coverage"]').textContent()) || '').trim()
    step('chart note says covers N of M work orders', /Covers \d+ of \d+ work orders/.test(coverage), coverage)

    const sub = page.locator('select[name="subcontractor"]')
    const values = (await sub.locator('option').evaluateAll((os) => os.map((o) => o.value))).filter(Boolean)
    step('subcontractor filter has options', values.length > 0, `${values.length} options`)
    await sub.selectOption(values[0])
    await page.waitForURL((u) => u.searchParams.get('subcontractor') === values[0], { timeout: 10000 })
    step('filter is kept in the URL', true)
    await page.waitForFunction((v) => [...document.querySelectorAll('[data-testid="plan-table"] tbody tr.order td:nth-child(3)')].every((td) => td.textContent.trim() === v), values[0], { timeout: 15000 })
    const tableRows = await page.locator('[data-testid="plan-table"] tbody tr.order').count()
    step('table shows only that subcontractor', tableRows > 0, `${tableRows} rows`)

    const [dl] = await Promise.all([page.waitForEvent('download'), page.click('[data-testid="export-csv"]')])
    const name = dl.suggestedFilename()
    step('CSV file name lutetia-plan-YYYY-MM-DD.csv', /^lutetia-plan-\d{4}-\d{2}-\d{2}\.csv$/.test(name), name)
    const text = fs.readFileSync(await dl.path(), 'utf8')
    step('CSV starts with a UTF-8 BOM', text.charCodeAt(0) === 0xfeff)
    const records = csvRecords(text.slice(1))
    step('table rows = CSV data rows', records.length - 1 === tableRows, `table ${tableRows}, csv ${records.length - 1}`)

    await page.click('[data-testid="clear-filters"]')
    await page.waitForURL((u) => !u.searchParams.has('subcontractor'), { timeout: 10000 })
    step('Clear filters empties the URL filter', true)
    // the URL changes before the rows are reloaded: wait for the unfiltered list, else the count below sees the old filtered rows
    await page.waitForLoadState('networkidle')
    await page.waitForFunction((n) => document.querySelectorAll('[data-testid="plan-table"] tbody tr.order').length !== n, tableRows, { timeout: 15000 }).catch(() => {})

    const withSegments = page.locator('[data-testid="plan-table"] tbody tr.order').filter({ hasNot: page.locator('td:nth-child(6)', { hasText: '—' }) })
    const n = await withSegments.count()
    step('a work order with cable segments is listed', n > 0, `${n}`)
    const toggle = withSegments.first().locator('button.expand')
    await toggle.click()
    await page.locator('[data-testid="segment-table"]').first().waitFor({ timeout: 15000 })
    step('expanded row: aria-expanded=true and segments appear', (await toggle.getAttribute('aria-expanded')) === 'true')

    const sla = page.locator('[data-testid="sla-reference"]')
    await sla.waitFor({ timeout: 10000 })
    await page.waitForSelector('[data-testid="sla-steps"], [data-testid="sla-empty"]', { timeout: 15000 })
    const slaText = ((await sla.textContent()) || '').replace(/\s+/g, ' ')
    step('SLA reference shown, marked reference only', /Reference only — not tracked per work order/.test(slaText))
    step('no Chinese text in the SLA reference', !/[\u4e00-\u9fff]/.test(slaText))

    const csp = await page.evaluate(() => window.__csp)
    if (csp.length) console.log('CSP violations:', csp)
    if (consoleErrors.length) console.log('console errors:', consoleErrors)
    step('CSP violations 0', csp.length === 0, String(csp.length))
    step('console errors 0', consoleErrors.length === 0, String(consoleErrors.length))
    console.log('ALL PASS')
    await browser.close()
    process.exit(0)
  } catch (e) {
    console.error(String(e))
    await browser.close()
    process.exit(1)
  }
}
main()
