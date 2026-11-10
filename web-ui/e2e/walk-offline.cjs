#!/usr/bin/env node
// Task 11.1 walk-through of offline use and Sign out (SC-11, DFX privacy), for the tester to run on fra / the local compose
// stack with the Playwright in ~/tools/pw:
//   BASE_URL=https://… WALK_USER=… WALK_PASSWORD=… node walk-offline.cjs
// Nothing real is written here: base URL, account and password come only from the environment. Read-only (GETs only, plus
// the sign-in and sign-out forms).
// Steps: sign in -> Overview loads -> the service worker controls the page -> reload once online so the API answers go
// through it and are saved -> offline -> reload -> data and "Offline · data as of HH:MM" still show, no red error banner ->
// Sign out while offline -> "Signing out needs a connection." and still on the page -> online -> Sign out -> caches.keys() is [] and no worker is registered -> offline, open /app/: no data (sign-in page with
// the offline notice, or the browser's own offline page because nothing of the app is left on the device).
// Console errors and CSP violations must be 0; while offline, the browser's own "net::ERR_INTERNET_DISCONNECTED" lines for
// requests that cannot be answered (/api/v1/me is never cached) are expected and listed apart.
// Exit 0 = every step passed, 1 = a step failed (the failing step is printed), 2 = missing environment or Playwright.
'use strict'

let chromium
try {
  ;({ chromium } = require('playwright'))
} catch (e) {
  console.error('walk-offline: Playwright not found (run from ~/tools/pw):', e.message)
  process.exit(2)
}

const BASE = (process.env.BASE_URL || '').replace(/\/+$/, '')
const USER = process.env.WALK_USER || ''
const PASSWORD = process.env.WALK_PASSWORD || ''
const WIDTH = Number(process.env.WALK_WIDTH || 390)
if (!BASE || !USER || !PASSWORD) {
  console.error('walk-offline: set BASE_URL, WALK_USER and WALK_PASSWORD')
  process.exit(2)
}
const OFFLINE_NOISE = /ERR_INTERNET_DISCONNECTED/

function step(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
  if (!ok) throw new Error(`step failed: ${name}`)
}

async function asOfText(page) {
  const el = page.locator('[data-testid="asof"]')
  await page.waitForFunction(() => !/—\s*$/.test(document.querySelector('[data-testid="asof"]')?.textContent || '—'), null, { timeout: 15000 })
  return ((await el.textContent()) || '').trim()
}

async function main() {
  const browser = await chromium.launch()
  const consoleErrors = []
  const offlineNoise = []
  try {
    const ctx = await browser.newContext({ viewport: { width: WIDTH, height: 844 }, locale: 'en-GB', serviceWorkers: 'allow' })
    const page = await ctx.newPage()
    page.on('console', (m) => {
      if (m.type() !== 'error') return
      ;(OFFLINE_NOISE.test(m.text()) ? offlineNoise : consoleErrors).push(m.text())
    })
    page.on('pageerror', (e) => consoleErrors.push(String(e)))
    await page.addInitScript(() => {
      window.__csp = []
      document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`))
    })
    const cspSoFar = []
    const collectCsp = async () => cspSoFar.push(...(await page.evaluate(() => window.__csp || [])))

    await page.goto(`${BASE}/app/signin?next=${encodeURIComponent('/app/')}`)
    await page.fill('input[name="username"]', USER)
    await page.fill('input[name="password"]', PASSWORD)
    await Promise.all([page.waitForURL((u) => !u.pathname.startsWith('/app/signin')), page.click('form button[type="submit"]')])
    const online1 = await asOfText(page)
    step('Overview loads online', true, online1)

    const controlled = await page.evaluate(async () => {
      await navigator.serviceWorker.ready
      if (!navigator.serviceWorker.controller) await new Promise((r) => navigator.serviceWorker.addEventListener('controllerchange', r, { once: true }))
      return navigator.serviceWorker.controller ? navigator.serviceWorker.controller.scriptURL : null
    })
    step('service worker controls the page from /app/', !!controlled && new URL(controlled).pathname === '/app/sw.js', String(controlled))
    await collectCsp()
    await page.reload()
    const online2 = await asOfText(page)
    const saved = await page.evaluate(async () => {
      const out = {}
      for (const n of await caches.keys()) out[n] = (await (await caches.open(n)).keys()).map((r) => new URL(r.url).pathname)
      return out
    })
    const api = saved['lutetia-api'] || []
    step('API answers saved, /api/v1/me not among them', api.some((p) => p === '/api/v1/summary') && !api.includes('/api/v1/me'), `${api.length} entries`)

    await collectCsp()
    await ctx.setOffline(true)
    await page.reload()
    const offline1 = await asOfText(page)
    step('offline reload still shows data', /\d{2}:\d{2}/.test(offline1), offline1)
    const banner = page.locator('[data-banner]')
    await banner.waitFor({ timeout: 15000 })
    const kind = await banner.getAttribute('data-banner')
    const text = ((await banner.textContent()) || '').replace(/\s+/g, ' ').trim()
    step('offline banner with the time of the saved data', kind === 'offline' && /^Offline · data as of \d{2}:\d{2}/.test(text), `${kind}: ${text}`)
    step('no red error banner or session error while offline', (await page.locator('[data-banner="error"], .notice[role="alert"]').count()) === 0)
    step('saved time equals the last online time', offline1 === online2, `${online2} -> ${offline1}`)

    // Sign out while offline: nothing posted, nothing cleared, the menu says it needs a connection
    const before = page.url()
    await page.locator('details.account summary').click()
    await page.locator('form[action="/logout"] button').click()
    const notice = page.locator('[data-testid="signout-offline"]')
    await notice.waitFor({ timeout: 5000 })
    const kept = await page.evaluate(async () => (await caches.keys()).length)
    step('offline Sign out: notice shown, still on the page, caches kept',
      /Signing out needs a connection/.test((await notice.textContent()) || '') && page.url() === before && kept > 0, `${kept} caches`)
    await page.locator('details.account summary').click() // close the menu again

    await collectCsp()
    await ctx.setOffline(false)
    await page.reload()
    await asOfText(page)
    await page.locator('details.account summary').click()
    await Promise.all([page.waitForURL((u) => u.pathname.startsWith('/app/signin')), page.locator('form[action="/logout"] button').click()])
    const left = await page.evaluate(async () => ({
      caches: await caches.keys(),
      workers: (await navigator.serviceWorker.getRegistrations()).length,
    }))
    step('after Sign out caches.keys() is empty', left.caches.length === 0, JSON.stringify(left.caches))
    step('after Sign out no service worker is registered', left.workers === 0, String(left.workers))

    await collectCsp()
    await ctx.setOffline(true)
    let opened = 'page'
    try {
      await page.goto(`${BASE}/app/`)
    } catch (e) {
      if (!OFFLINE_NOISE.test(String(e))) throw e
      opened = 'browser offline page'
    }
    if (opened === 'page') {
      await collectCsp()
      const url = new URL(page.url())
      const main = await page.locator('body').innerText()
      step('offline after Sign out: sign-in page, not data', url.pathname.startsWith('/app/signin') && /Sign in needs a connection/.test(main), url.pathname)
      step('offline after Sign out: no data shown', (await page.locator('[data-testid="asof"]').count()) === 0)
    } else {
      step('offline after Sign out: nothing of the app left, browser shows its offline page', true)
    }
    await ctx.setOffline(false)

    if (offlineNoise.length) console.log('expected offline lines:', offlineNoise)
    if (cspSoFar.length) console.log('CSP violations:', cspSoFar)
    if (consoleErrors.length) console.log('console errors:', consoleErrors)
    step('CSP violations 0', cspSoFar.length === 0, String(cspSoFar.length))
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
