#!/usr/bin/env node
// Task 9.3 walk-through of Overview -> Manholes drawer, for the tester to run on fra with the Playwright in ~/tools/pw:
//   BASE_URL=https://… WALK_USER=… WALK_PASSWORD=… node walk-manholes.cjs
// Nothing real is written here: base URL, account and password come only from the environment. Read-only: the page only
// GETs; the one interception below answers /api/v1 with a synthetic 503 inside this browser, nothing reaches the server.
// Steps: sign in -> Overview -> click the newest event -> drawer shows that IMEI and "Location unverified" -> Esc closes,
// focus is back on that event row -> /api/v1 answers 503 -> red error banner, old data still on screen -> reduced motion:
// .pulse animation-name is none -> console errors and CSP violations are both 0.
// Exit 0 = every step passed, 1 = a step failed (the failing step is printed), 2 = missing environment or Playwright.
'use strict'

let chromium
try {
  ;({ chromium } = require('playwright'))
} catch (e) {
  console.error('walk-manholes: Playwright not found (run from ~/tools/pw):', e.message)
  process.exit(2)
}

const BASE = (process.env.BASE_URL || '').replace(/\/+$/, '')
const USER = process.env.WALK_USER || ''
const PASSWORD = process.env.WALK_PASSWORD || ''
const WIDTH = Number(process.env.WALK_WIDTH || 1440)
if (!BASE || !USER || !PASSWORD) {
  console.error('walk-manholes: set BASE_URL, WALK_USER and WALK_PASSWORD')
  process.exit(2)
}

const results = []
function step(name, ok, detail = '') {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
  if (!ok) throw new Error(`step failed: ${name}`)
}

async function collect(page, consoleErrors) {
  page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
  page.on('pageerror', (e) => consoleErrors.push(String(e)))
  await page.addInitScript(() => {
    window.__csp = []
    document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`))
  })
}

async function signIn(page) {
  await page.goto(`${BASE}/app/signin?next=${encodeURIComponent('/app/')}`)
  await page.fill('input[name="username"]', USER)
  await page.fill('input[name="password"]', PASSWORD)
  await Promise.all([page.waitForURL((u) => !u.pathname.startsWith('/app/signin')), page.click('form button[type="submit"]')])
}

async function main() {
  const browser = await chromium.launch()
  const consoleErrors = []
  let cspTotal = 0
  try {
    // ---- normal motion: overview, drawer, focus return, 503 -------------------------------------------------------------
    const ctx = await browser.newContext({ viewport: { width: WIDTH, height: 900 } })
    const page = await ctx.newPage()
    await collect(page, consoleErrors)
    await signIn(page)
    await page.waitForSelector('.statusstrip', { timeout: 15000 })
    step('overview shows the status strip', true)
    const first = page.locator('.event').first()
    await first.waitFor({ timeout: 15000 })
    const deviceId = await first.getAttribute('data-device')
    const imei = ((await first.locator('.top .mono').textContent()) || '').trim() // what the row shows: the IMEI (name), never the device id
    step('overview lists a newest event', !!deviceId && !!imei, imei || 'no event row (the database has no fall events?)')
    const nameApi = await page.evaluate(async (d) => {
      const r = await fetch('/api/v1/manholes?limit=1000', { credentials: 'same-origin' })
      const j = await r.json()
      const m = (j.items || []).find((x) => x.device_id === d)
      return m ? m.name : null
    }, deviceId)
    step('event row shows the manhole name (IMEI), device id only as fallback', imei === (nameApi || deviceId), `${imei} / name ${nameApi} / id ${deviceId}`)
    await first.click()
    const drawer = page.locator('dialog[data-testid="manhole-drawer"][open]')
    await drawer.waitFor({ timeout: 15000 })
    const title = (await drawer.locator('#drawer-title').textContent()) || ''
    step('drawer opens on that IMEI', title.trim() === imei, title.trim())
    const unverified = await drawer.getByText(/Location unverified|Position non vérifiée/).count()
    step('drawer says "Location unverified"', unverified > 0)
    await page.locator('.timeline .event').first().waitFor({ state: 'attached', timeout: 15000 }) // the timeline loads right after the page opens; Esc before that has no event bar to give focus to
    await page.keyboard.press('Escape')
    await page.waitForSelector('dialog[data-testid="manhole-drawer"]:not([open])', { state: 'attached', timeout: 5000 })
    const focused = await page.evaluate(() => {
      const a = document.activeElement
      return a ? { cls: a.className, device: a.getAttribute('data-device') } : null
    })
    step('Esc closes, focus is back on the event row', !!focused && /\bevent\b/.test(String(focused.cls)) && focused.device === deviceId, JSON.stringify(focused))

    const listRows = await page.locator('[data-testid="manhole-list"] .row').count()
    step('CMP-7 list: every manhole has a row (also without position)', listRows > 0, `${listRows} rows`)
    await page.locator('.event').first().waitFor({ timeout: 15000 }) // the Manholes timeline loads after the drawer closes; count only once it is on screen
    const before = await page.locator('.event').count()
    await page.route('**/api/v1/**', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"synthetic 503"}' }))
    await page.evaluate(() => window.dispatchEvent(new Event('online'))) // the page refreshes at once on "online"
    const banner = page.locator('[data-banner="error"]')
    await banner.waitFor({ timeout: 70000 }) // at the latest the next 60 s refresh
    const red = await banner.evaluate((el) => getComputedStyle(el).color)
    const errColor = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-error').trim())
    const expected = await page.evaluate((c) => {
      const probe = document.createElement('span')
      probe.className = 'probe-error'
      probe.setAttribute('data-probe', '1')
      document.body.appendChild(probe)
      probe.style.setProperty('color', c)
      const rgb = getComputedStyle(probe).color
      probe.remove()
      return rgb
    }, errColor)
    step('503 shows the error banner in --color-error', red === expected, `color ${red}, --color-error ${errColor} = ${expected}`)
    const after = await page.locator('.event').count()
    step('old data stays on screen', after === before && after > 0, `${before} -> ${after} event rows`)
    await page.unroute('**/api/v1/**')
    cspTotal += await page.evaluate(() => window.__csp.length)
    const cspList = await page.evaluate(() => window.__csp)
    if (cspList.length) console.log('CSP violations:', cspList)
    await ctx.close()

    // ---- reduced motion: no pulse animation ------------------------------------------------------------------------------
    const rctx = await browser.newContext({ viewport: { width: WIDTH, height: 900 }, reducedMotion: 'reduce' })
    const rpage = await rctx.newPage()
    await collect(rpage, consoleErrors)
    await signIn(rpage)
    await rpage.goto(`${BASE}/app/manholes`)
    await rpage.waitForSelector('.mh-marker', { timeout: 15000 })
    // live.ts never adds .pulse under reduced motion, so put it on one marker by hand and read what CSS makes of it
    const anim = await rpage.evaluate(() => {
      const m = document.querySelector('.mh-marker')
      m.classList.add('pulse')
      const shape = m.querySelector('.shape')
      return getComputedStyle(shape).animationName
    })
    step('reduced motion: .pulse animation-name is none', anim === 'none', anim)
    cspTotal += await rpage.evaluate(() => window.__csp.length)
    await rctx.close()

    // 503s answered on purpose above show up as failed-resource console errors: they are not counted
    const real = consoleErrors.filter((m) => !/503|synthetic 503|security data refresh failed|movement events load failed/.test(m))
    if (real.length) console.log('console errors:', real)
    step('console errors 0', real.length === 0, String(real.length))
    step('CSP violations 0', cspTotal === 0, String(cspTotal))
  } finally {
    await browser.close()
  }
}

main().then(
  () => {
    console.log(`walk-manholes: ${results.length} steps passed`)
    process.exit(0)
  },
  (e) => {
    console.error('walk-manholes:', e.message)
    process.exit(1)
  },
)
