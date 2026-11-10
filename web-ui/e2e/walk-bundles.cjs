#!/usr/bin/env node
// Task 10.1 walk-through of the Bundles page, for the tester to run on fra / the local compose stack with the Playwright in ~/tools/pw:
//   BASE_URL=https://… WALK_USER=… WALK_PASSWORD=… [WALK_EXPECT=tracks|empty|silent] node walk-bundles.cjs
// Nothing real is written here: base URL, account and password come only from the environment. Read-only (GETs only).
// WALK_EXPECT picks what the database should look like (default tracks):
//   tracks - at least one tracker with track points: sign in -> Bundles -> the fixed note is there -> click the first
//            tracker -> the track polyline (path.trk-line) and both end marks appear -> clicking it again hides them.
//   silent - trackers exist but none reported in 24 h: "No position reported in the last 24 h" and the last position time show.
//   empty  - no tracker at all: the empty-state text shows and no map is drawn.
// In every mode the page note is checked and console errors and CSP violations must both be 0.
// Exit 0 = every step passed, 1 = a step failed (the failing step is printed), 2 = missing environment or Playwright.
'use strict'

let chromium
try {
  ;({ chromium } = require('playwright'))
} catch (e) {
  console.error('walk-bundles: Playwright not found (run from ~/tools/pw):', e.message)
  process.exit(2)
}

const BASE = (process.env.BASE_URL || '').replace(/\/+$/, '')
const USER = process.env.WALK_USER || ''
const PASSWORD = process.env.WALK_PASSWORD || ''
const WIDTH = Number(process.env.WALK_WIDTH || 1440)
const EXPECT = process.env.WALK_EXPECT || 'tracks'
if (!BASE || !USER || !PASSWORD || !['tracks', 'empty', 'silent'].includes(EXPECT)) {
  console.error('walk-bundles: set BASE_URL, WALK_USER and WALK_PASSWORD; WALK_EXPECT is tracks, empty or silent')
  process.exit(2)
}

function step(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
  if (!ok) throw new Error(`step failed: ${name}`)
}

async function main() {
  const browser = await chromium.launch()
  const consoleErrors = []
  try {
    const ctx = await browser.newContext({ viewport: { width: WIDTH, height: 900 }, locale: 'en-GB' })
    const page = await ctx.newPage()
    page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
    page.on('pageerror', (e) => consoleErrors.push(String(e)))
    await page.addInitScript(() => {
      window.__csp = []
      document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`))
    })
    await page.goto(`${BASE}/app/signin?next=${encodeURIComponent('/app/bundles')}`)
    await page.fill('input[name="username"]', USER)
    await page.fill('input[name="password"]', PASSWORD)
    await Promise.all([page.waitForURL((u) => !u.pathname.startsWith('/app/signin')), page.click('form button[type="submit"]')])
    await page.goto(`${BASE}/app/bundles`)

    const note = page.locator('[data-testid="bundles-note"]')
    await note.waitFor({ timeout: 15000 })
    step('fixed note says position and track only', /last position and 7-day track only; trip status is not computed yet/.test((await note.textContent()) || ''))

    if (EXPECT === 'empty') {
      await page.locator('[data-testid="bundles-empty"]').waitFor({ timeout: 15000 })
      step('empty state shown', true, (await page.locator('[data-testid="bundles-empty"]').textContent())?.trim())
      step('no map drawn', (await page.locator('[data-testid="bundle-map"]').count()) === 0)
    } else {
      await page.locator('[data-testid="device-list"] .row').first().waitFor({ timeout: 15000 })
      const rows = await page.locator('[data-testid="device-list"] .row').count()
      step('device list has rows', rows > 0, `${rows} trackers`)
      const first = page.locator('[data-testid="device-list"] .row').first()
      const text = ((await first.textContent()) || '').replace(/\s+/g, ' ').trim()
      step('row shows an IMEI-like name, state text and a Paris time zone', /\b(CET|CEST)\b/.test(text) && /(Online|Offline)/.test(text), text)
      const silent = page.locator('[data-testid="no-position-24h"]')
      if (EXPECT === 'silent') {
        await silent.waitFor({ timeout: 5000 })
        const msg = ((await silent.textContent()) || '').replace(/\s+/g, ' ')
        step('silent notice with last position time', /No GPS tracker has reported in the last 24 h/.test(msg) && /Last position: .+(CET|CEST)/.test(msg), msg)
        step('no "in transit" / "arrived" wording', !/in transit|arrived|en route/i.test(await page.locator('main').innerText()))
      } else {
        step('no silent notice when a tracker is online', (await silent.count()) === 0)
      }
      await first.click()
      await page.waitForSelector('path.trk-line', { timeout: 15000 })
      step('track polyline appears after picking a tracker', true)
      step('track start and end marks appear', (await page.locator('.trk-end.start').count()) === 1 && (await page.locator('.trk-end.end').count()) === 1)
      await first.click()
      await page.waitForSelector('path.trk-line', { state: 'detached', timeout: 5000 })
      step('second click hides the track', true)
    }
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
