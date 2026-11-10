#!/usr/bin/env node
// Phase 12 walk-through of the embedded widgets (SC-15, THR-2 / THR-3, ADR-6), for the tester to run on fra with the Playwright
// in ~/tools/pw:
//   BASE_URL=https://iot.digifiber.net WALK_USER=… WALK_PASSWORD=… node walk-embed.cjs
// How two same-site host names are obtained without DNS or certificates: the host pages are served by Playwright request
// interception (page.route) at https://test-host.digifiber.net/ (allowed) and https://evil.example/ (not allowed); the browser
// treats them as those origins, so the Lutetia session cookie (SameSite=Lax) is same-site for the first and not for the second.
// BASE_URL must therefore be on digifiber.net. For a local stack instead, map the name to it and accept its self-signed cert:
//   WALK_RESOLVE="MAP iot.digifiber.net 127.0.0.1:8443" BASE_URL=https://iot.digifiber.net … (adds --host-resolver-rules and
//   ignoreHTTPSErrors).
// Nothing real is written here: base URL, account and password come only from the environment. Read-only (GETs, plus the
// sign-in form). deploy/embed-test-host.html is the host page (no credential in it).
// Steps: signed out -> every widget shows "Sign in to Lutetia to see this." with a new-tab link and no input field -> sign in at
// BASE -> the host reloads -> the timeline shows events (or its empty line), the map and the summary show -> click the first
// event -> the host receives {type: lutetia:fall-event-selected, v: 1, device_id, imei, started_at} and lutetia:resize, with no
// position field -> no service worker controls the widget and none is registered for /embed/ -> evil.example frames the
// timeline: the browser refuses (the frame never loads the widget) -> /app/ framed by test-host is refused too.
// Exit 0 = every step passed, 1 = a step failed (the failing step is printed), 2 = missing environment or Playwright.
'use strict'

const fs = require('fs')
const path = require('path')

let chromium
try {
  ;({ chromium } = require('playwright'))
} catch (e) {
  console.error('walk-embed: Playwright not found (run from ~/tools/pw):', e.message)
  process.exit(2)
}

const BASE = (process.env.BASE_URL || '').replace(/\/+$/, '')
const USER = process.env.WALK_USER || ''
const PASSWORD = process.env.WALK_PASSWORD || ''
const RESOLVE = process.env.WALK_RESOLVE || ''
const RANGE = ['24h', '7d', '30d'].includes(process.env.WALK_RANGE) ? process.env.WALK_RANGE : '30d' // timeline range to walk
if (!BASE || !USER || !PASSWORD) {
  console.error('walk-embed: set BASE_URL, WALK_USER and WALK_PASSWORD')
  process.exit(2)
}
if (!/^https:\/\/[a-z0-9.-]+\.digifiber\.net$/.test(BASE)) {
  console.error('walk-embed: BASE_URL must be https://<name>.digifiber.net (see WALK_RESOLVE in the header for a local stack)')
  process.exit(2)
}
const HOST = 'https://test-host.digifiber.net'
const EVIL = 'https://evil.example'
const HOST_HTML = fs.readFileSync(path.join(__dirname, '..', '..', 'deploy', 'embed-test-host.html'), 'utf8')
const WIDGETS = ['fall-timeline', 'manhole-map', 'security-summary']
const SIGNIN_TEXT = 'Sign in to Lutetia to see this.'

function step(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
  if (!ok) throw new Error(`step failed: ${name}`)
}

function frameOf(page, name) {
  return page.frameLocator(`iframe#${name}`)
}

async function main() {
  // A loopback target makes Chromium treat the faked public host page as reaching a local network and block its iframes
  // (ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS); the flags only matter for a WALK_RESOLVE stack, not for a real DNS name.
  const args = RESOLVE
    ? [`--host-resolver-rules=${RESOLVE}`, '--disable-features=LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessForNavigations,PrivateNetworkAccessForWorkers']
    : []
  const browser = await chromium.launch({ args })
  const errors = []
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: 'en-GB', ignoreHTTPSErrors: !!RESOLVE })
    // The two host pages exist only inside this browser.
    await ctx.route(`${HOST}/**`, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: HOST_HTML }))
    await ctx.route(`${EVIL}/**`, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: HOST_HTML }))
    const page = await ctx.newPage()
    page.on('pageerror', (e) => errors.push(String(e)))
    const hostUrl = `${HOST}/?base=${encodeURIComponent(BASE)}&lang=en&range=${RANGE}`

    // 1. Signed out
    await page.goto(hostUrl)
    for (const w of WIDGETS) {
      const f = frameOf(page, w)
      await f.locator('[data-embed-signin]').waitFor({ timeout: 20000 })
      const text = (await f.locator('[data-embed-signin]').textContent()) || ''
      const link = f.locator('[data-embed-signin] a')
      step(`${w}: sign-in prompt when signed out`, text.includes(SIGNIN_TEXT))
      step(`${w}: link opens a new tab`, (await link.getAttribute('target')) === '_blank' && /noopener/.test((await link.getAttribute('rel')) || ''))
      step(`${w}: no input field at all`, (await f.locator('input, textarea, select, form').count()) === 0)
    }

    // 2. Sign in at Lutetia itself (first-party), then reload the host
    const login = await ctx.newPage()
    await login.goto(`${BASE}/app/signin?next=${encodeURIComponent('/app/')}`)
    await login.fill('input[name="username"]', USER)
    await login.fill('input[name="password"]', PASSWORD)
    await Promise.all([login.waitForURL((u) => !u.pathname.startsWith('/app/signin')), login.click('form button[type="submit"]')])
    await login.close()
    await page.bringToFront()
    await page.reload()

    const tl = frameOf(page, 'fall-timeline')
    await tl.locator('section .rows, section .none').first().waitFor({ timeout: 20000 })
    step('signed in: the timeline shows (session cookie sent in the same-site iframe)', (await tl.locator('[data-embed-signin]').count()) === 0)
    await frameOf(page, 'manhole-map').locator('[data-testid="manhole-map"]').waitFor({ timeout: 20000 })
    step('signed in: the map shows', true)
    await frameOf(page, 'security-summary').locator('.statusstrip').waitFor({ timeout: 20000 })
    step('signed in: the summary shows, without links', (await frameOf(page, 'security-summary').locator('.statusstrip a').count()) === 0)

    // 3. Messages
    const rows = tl.locator('button.event')
    // No event in the range means the message path was not exercised: that is a failed walk, not a pass (run with a wider
    // WALK_RANGE, e.g. 30d, on a server that has events).
    step('the timeline has at least one event to click', (await rows.count()) > 0, `range ${RANGE}; set WALK_RANGE=30d if empty`)
    {
      await rows.first().click()
      await page.waitForFunction(() => window.received.some((m) => m.data.type === 'lutetia:fall-event-selected'), null, { timeout: 5000 })
      const msg = await page.evaluate(() => window.received.find((m) => m.data.type === 'lutetia:fall-event-selected').data)
      step('host received fall-event-selected v1', msg.v === 1 && typeof msg.device_id === 'string' && typeof msg.imei === 'string' && typeof msg.started_at === 'string', JSON.stringify(msg))
      step('the message has no position', !('lat' in msg) && !('lon' in msg) && Object.keys(msg).length === 5)
      step('neither the widget nor the host navigated', page.url().startsWith(HOST) && page.frames().some((f) => f.url().startsWith(`${BASE}/embed/fall-timeline`)))
    }
    await page.waitForFunction(() => window.received.some((m) => m.data.type === 'lutetia:resize'), null, { timeout: 5000 })
    step('host received lutetia:resize', true)

    // 4. No service worker for the widgets
    const embedFrame = page.frames().find((f) => f.url().startsWith(`${BASE}/embed/`))
    const sw = await embedFrame.evaluate(async () => ({
      controlled: !!(navigator.serviceWorker && navigator.serviceWorker.controller),
      forEmbed: navigator.serviceWorker ? !!(await navigator.serviceWorker.getRegistration('/embed/')) : false,
      manifest: !!document.querySelector('link[rel="manifest"]'),
    }))
    step('no service worker controls or is registered for /embed/, no manifest link', !sw.controlled && !sw.forEmbed && !sw.manifest, JSON.stringify(sw))

    // 5. Hosts that may not frame
    const evil = await ctx.newPage()
    const refused = []
    evil.on('console', (m) => refused.push(m.text()))
    await evil.goto(`${EVIL}/?base=${encodeURIComponent(BASE)}&lang=en`)
    await evil.waitForTimeout(4000)
    const evilWidget = evil.frames().find((f) => f.url().startsWith(`${BASE}/embed/fall-timeline`))
    const rendered = evilWidget ? await evilWidget.evaluate(() => !!document.querySelector('#embed > *')).catch(() => false) : false
    step('evil.example cannot frame the widget (frame-ancestors)', !rendered, refused.filter((t) => /frame-ancestors|refused/i.test(t)).slice(0, 1).join(' '))
    await evil.close()

    const app = await ctx.newPage()
    await app.route(`${HOST}/app-frame`, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: `<iframe id="a" src="${BASE}/app/"></iframe>` }))
    await app.goto(`${HOST}/app-frame`)
    await app.waitForTimeout(3000)
    const appFrame = app.frames().find((f) => f.url().startsWith(`${BASE}/app/`))
    const appRendered = appFrame ? await appFrame.evaluate(() => !!document.querySelector('#app > *')).catch(() => false) : false
    step('/app/ cannot be framed even by a digifiber.net host', !appRendered)

    step('no page error in the widgets', errors.length === 0, errors.join(' | '))
  } finally {
    await browser.close()
  }
}

main().then(
  () => process.exit(0),
  (e) => {
    console.error(String(e))
    process.exit(1)
  },
)
