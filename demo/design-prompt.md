# Build: "Ariane · Copper Watch" — interactive prototype (single HTML file)

You are building the full interactive design prototype of a read-only security and project dashboard for a copper-cable removal project in France. It is the reference developers will implement from, and what stakeholders will open in a browser. Everything you need is below. Follow DESIGN.md (included verbatim further down) exactly: its tokens override the base design system's defaults. Do not use any colour, size or radius that is not a DESIGN.md token.

## What the product is for (read this first)
- The contractor is liable for any copper theft during the works. The dashboard is first a theft-detection line of defence and an evidence record, and only second a view of the removal plan.
- Two device kinds: **manhole sensors** (Dingtek, magnet-mounted on manhole covers, report tilt = "the cover was moved") and **copper-bundle GPS trackers** (GPS51 car trackers strapped to ~250 kg copper bundles carried from site to warehouse).
- Users: project managers (Orange) glancing on an iPhone for a few seconds, possibly offline; the Huawei project team at desks checking work orders; occasionally projected in a meeting room; small widgets embedded inside another system's light-themed pages.
- Design principles: (1) calm until something happens — the UI is grey; only "moved", "moving now", "offline", "data delayed" get colour; (2) the map and the events are the protagonists, numbers are secondary; (3) every block carries its context (device / work-order ID, event time with time zone, "as of" time) so a screenshot explains itself.
- Interface languages: English and French only (never Chinese). Default follows the browser (French browser → French, everything else → English); a manual EN | FR switch. Dates, times and numbers formatted per language; all times shown in Europe/Paris with the zone abbreviation.

## Screens to build (all of them, each with its states)
Navigation: desktop top bar — left "Ariane · Copper Watch"; tabs Overview / Manholes / Bundles / Plan; right: "As of 08:42 CET", theme switch (Dark / Projection), EN | FR, account menu with Sign out. Mobile (≤ 600 px): top line with project name and "As of"; bottom tab bar Overview / Manholes / Bundles / Plan; touch targets ≥ 44 px; no horizontal scroll at 375 px. URL hash reflects tab, filters and selected device.

### SCREEN-1 Overview
- First thing on screen: **Security status strip** (three columns): "1 moved in last 24 h" (amber, triangle icon), "2 offline" (grey, hollow slashed circle), "9 online" (neutral, no colour). Each is a link to Manholes (the first filters to moved manholes). "As of 08:42 CET".
- Next to it: the 3 latest movement events (event rows) and a compact map with the 12 manholes.
- Then one line for copper bundles: "5 trackers · 0 online · last position Wed 14 Oct, 11:43 CET" with a "View bundles" text link.
- Bottom: removal-plan summary: "117 work orders · 25 with cable detail · 244.4 t planned (weight pending for 92 of 117)" plus the source note "Excel snapshot, as of 8 Nov 05:12 · Ariane is the source of truth" and an "Open plan" link. No OCC schedule strip on the overview (OCC is viewed in Ariane).
- Empty/good state: "All 12 manholes quiet since Sun 8 Nov, 02:20 CET".

### SCREEN-2 Manholes
- Map takes about two thirds of the width (top half on mobile); movement-event timeline on the right (bottom on mobile), newest first. Range switch 24 h | 7 d | 30 d. Toggle "Only manholes with events".
- Marker states (colour + shape, never colour alone): normal = neutral filled circle; moved within 24 h = amber triangle; moving now = red filled triangle; offline = grey hollow circle with a slash; selected = thicker outline. Each manhole marker has a small "unverified" corner mark and the list says "Location unverified" (positions are not confirmed yet).
- Event row: IMEI (mono), start time to the second with zone (mono), duration, number of flips, a reserved "Notified: —" slot.
- Clicking an event or a marker focuses the map on it and opens the **manhole drawer** from the right (full-height bottom sheet on mobile): IMEI, status, "Location unverified", last report, voltage, signal (RSRP), 7 d / 30 d line charts for voltage and signal (simple inline SVG charts, neutral strokes), and that manhole's events. Esc closes it and returns focus.
- Map: draw a schematic street-grid / area map in inline SVG (no tile service, no external map library); keep it calm grey; markers on top. It must look like a real map area around Carquefou (outskirts of Nantes): a few road lines, a river, place labels.
- Empty: "No movement in the last 7 days" with the map still shown.

### SCREEN-3 Bundles
- Same skeleton as Manholes: map (schematic) with the 5 GPS trackers' last positions and an optional "Show 7-day track" polyline; device list with ID (mono), status, last position time.
- A note at the top: "Shows last position and 7-day track only. Trip status (departed / in transit / arrived) is not computed yet."
- Realistic current state is the empty one: "No GPS tracker has reported in the last 24 h", still showing each tracker's last known position and time.

### SCREEN-4 Plan
- Source note at the top (as above).
- Filter bar: UCI, Subcontractor, Commune, Category (Transport / Distribution), Underground / Aerial, Cable type. Selected filters appear as removable tags; "Clear filters".
- Two horizontal bar charts: planned tonnes by subcontractor and by cable type (neutral bars, no gradients), caption "Covers the 25 of 117 work orders that have cable detail".
- Work-orders table: POI, UCI, Subcontractor, Commune, Category, Segments, Length (km), Planned (t), Received, Planned op date, OCC (raw text) with an "Open in Ariane" link. Rows without cable detail show "weight pending" (never 0). Rows expand to show cable segments (category, cable type, infrastructure, length, weight). "Export filtered rows (CSV)" primary button really generates a CSV in the browser.
- SLA reference: one small flow per category (Transportation / Distribution / Massive), labelled "Reference only — not tracked per work order".
- Empty: "No work order matches these filters." with "Clear filters".
- Mobile: charts become a horizontally swipeable pair; table becomes compact rows (POI, subcontractor, tonnes, expand).

### SCREEN-5 Sign in
- Narrow centred form, project name above, Username, Password, "Keep me signed in for 30 days", primary "Sign in", EN | FR below. Errors: "Wrong username or password." Offline: "You're offline. Sign in needs a connection."

### SCREEN-E1 / E2 / E3 Embedded widgets (light theme, no navigation, width 360–720 px)
- E1 movement-event timeline, E2 manhole map, E3 one-line security status strip. Each shows "As of".
- Signed-out state: "Sign in to Lutetia to see this." with an "Open sign-in" button (would open a new window — show a note in the prototype). Never show a password field inside a widget.
- Show them inside a mock host page frame titled "Host page (Ariane) — example" with a light background, to demonstrate how they sit in a light host.

## Global states (every screen and widget)
Loading: grey skeleton shaped like the final content (no spinner). Offline: keep last data, neutral banner "Offline · data as of 08:42" (FR "Hors ligne · données de 08:42"). Data delayed: amber banner "Data may be delayed — collector last seen 07:51". Error: red banner "Couldn't load events. Retrying in 60 s — or reload now.", old data kept with its "as of". Signed out: go to Sign in. Only one banner at a time, the most severe wins. Not applicable: conflict, AI working.

## Prototype controls (prototype only — clearly marked, not a product feature)
A small collapsible panel at the bottom-right titled "Prototype controls" with: account (orange / huawei / admin), theme (Dark / Light / Projection = light with one type step larger), language (EN / FR), state (Normal / All quiet / Loading / Offline / Data delayed / Error / Signed out), "Simulate new movement event" (adds an event for 864317087590111 and plays the one choreographed pulse on its marker), view (App / Embedded widgets), and "Reset prototype". State the simulation boundaries in the panel: nothing is sent to a server, nothing is persisted, refresh resets everything, CSV export is real but contains only this synthetic data.

## Synthetic data (use exactly; it is fictional)
- Manholes (12): IMEIs 864317087590101 … 864317087590112. 864317087590107 moved: start Sun 8 Nov 2026 02:14:07 CET, 6 min, 9 flips. 864317087590103 moved Sat 7 Nov 23:51:40 CET, 2 min, 3 flips. 864317087590110: moving now (started 08:39:12 CET, ongoing). 864317087590104 and 864317087590112 offline (last report Thu 5 Nov). Others normal. Voltage 3.57–3.60 V, RSRP −89 to −104 dBm, last report within the last hour. Also show older events over 7 / 30 days (about 8 more spread out).
- GPS trackers (5): 4072400634 (last Wed 14 Oct 11:43 CET), 4072400915 (Mon 19 Oct 08:41 CET), 4072401353 (Fri 7 Aug), 4072407731 (Tue 30 Jun), 4072407783 (never reported). All currently offline.
- Work orders: show about 30 rows of the 117 (POI numbers like BRG600101, RNT600102, CHT600103, VFC600104 …), UCIs "AURA" and "OUEST", subcontractors "Hovia", "AB RSX", "RC", communes Carquefou, Guérande, Le Pouliguen, Miribel, Meximieux, Villefranche-sur-Saône, Anse, Lentilly; categories Transport / Distribution; cable types like "L1T 112", "L4T 56", "P 28/10"; about 10 rows with segments and tonnes (1.2–14.6 t), the rest "weight pending"; OCC texts like "OCC S48 - S49 2026/11/23 - 12/01" or empty.
- French strings: Overview → Vue d'ensemble, Manholes → Regards, Bundles → Tourets, Plan → Plan, Sign in → Se connecter, Movement event → Événement de déplacement, Weight pending → Poids en attente, Location unverified → Position non vérifiée, As of → Données de, Moved in last 24 h → Déplacés (24 h), Offline → Hors ligne, Online → En ligne, Export filtered rows (CSV) → Exporter les lignes filtrées (CSV), Open in Ariane → Ouvrir dans Ariane, Excel snapshot … Ariane is the source of truth → Instantané Excel … Ariane fait foi. Translate the remaining UI text yourself in the same plain, factual tone.

## Quality floor (must, without announcing it)
Keyboard reachable with visible focus (2 px outline); tabs and timeline navigable by keyboard; Esc closes the drawer and returns focus; touch targets ≥ 44 px on mobile; contrast ≥ 4.5:1 for text in both themes; state never by colour alone; prefers-reduced-motion stops the pulse and all transitions; tabular numerals for numbers; use the "…" character, not "..."; no horizontal scroll at 375 px; `max-width: 65ch` for running text; sentence case everywhere (no all-caps labels).

## Do not
Neon, glows, gradients, 3D, glassmorphism; rows of big number cards; indigo/purple; acid green; #0B0B0B / #111 fake black; all-caps eyebrow labels; "A · B · C" metadata chains (lay metadata out in aligned columns instead); arrows trailing links or buttons; fade-and-slide on load; nested cards; one radius everywhere; green for "online"; Chinese text; any external resource.

---

## DESIGN.md (verbatim — tokens override the base design system)

---
version: alpha
name: Ariane · Copper Watch
description: A security operator's console in matte graphite — a site-security control room at night, where the screen stays grey and quiet until a manhole moves, and then exactly that one point turns amber.
colors:
  primary: "#E8EBEF"
  on-primary: "#15181C"
  secondary: "#7E8792"
  neutral: "#15181C"
  surface: "#1C2025"
  surface-raised: "#252A31"
  on-surface: "#E8EBEF"
  on-surface-muted: "#A2AAB5"
  border: "#343B44"
  success: "#5CB98A"
  warning: "#F0A73A"
  error: "#F26B66"
  offline: "#7E8792"
typography:
  display:
    fontFamily: IBM Plex Sans
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0em
  headline-md:
    fontFamily: IBM Plex Sans
    fontSize: 18px
    fontWeight: 600
    lineHeight: 1.3
  body-md:
    fontFamily: IBM Plex Sans
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.5
  body-mobile:
    fontFamily: IBM Plex Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
  label-sm:
    fontFamily: IBM Plex Sans
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.4
  mono:
    fontFamily: IBM Plex Mono
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
rounded:
  none: 0px
  sm: 4px
  md: 6px
  lg: 8px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  gutter: 16px
  section: 32px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.sm}"
    padding: 8px 16px
    height: 36px
  button-primary-hover:
    backgroundColor: "#FFFFFF"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.sm}"
    padding: 8px 16px
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.sm}"
    padding: 10px
    height: 44px
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "{spacing.lg}"
  status-moved:
    backgroundColor: "{colors.warning}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
  status-moving:
    backgroundColor: "{colors.error}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
  status-offline:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.on-surface-muted}"
    rounded: "{rounded.sm}"
  event-row:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body-md}"
    padding: 8px 12px
  drawer:
    backgroundColor: "{colors.surface-raised}"
    rounded: "{rounded.none}"
    padding: "{spacing.xl}"
---

## Overview

Picture the site-security room of a utility contractor at 02:14 on a Sunday: a wall map of the district, a strip of recent events down the side, everything a dim graphite grey. Nothing on screen asks for attention — until one manhole cover is lifted, and that single point turns amber and pulses three times. That is the whole personality: calm, exact, and loud only about the one thing that matters. The reference is a security operator's console (Verkada Command's "map plus timeline"), not a sci-fi HUD.

The audience is project managers (Orange) and engineers (Huawei project team), on a phone in the metro for a few seconds, or at a desk for half an hour checking work orders. The interface is English or French, never Chinese. Density is tight on desktop tables, relaxed on phones, enlarged in projection mode.

There is no brand colour and no logo — only the project name. Colour is reserved for state.

## Colors

One system: a cool graphite neutral ramp with no accent hue; three state hues (amber, red, grey) carry all meaning, always paired with an icon shape and a word.

- **Primary ({colors.primary})**: near-white, used only for the single primary button on a screen (Sign in, Export). Never used for selection, links or charts — selection is shown with brightness and a heavier outline.
- **Secondary ({colors.secondary})**: borders of inputs, axis lines, metadata such as "as of" times. Not for body text.
- **Neutral ({colors.neutral}) / Surface ({colors.surface}) / Surface raised ({colors.surface-raised})**: the background, panels and the drawer. Layers are separated by these three brightness steps and hairline {colors.border}, not by shadows.
- **On-surface ({colors.on-surface}) / muted ({colors.on-surface-muted})**: primary text and secondary text; muted is still ≥ 4.5:1 on {colors.neutral}.
- **Warning ({colors.warning})**: amber — a manhole moved within the last 24 h, and the "data may be delayed" banner. Always with a triangle icon. Never decorative.
- **Error ({colors.error})**: red — a movement still in progress, and errors. Always with a filled triangle or error icon.
- **Offline ({colors.offline})**: grey with a hollow, slashed marker — a device that stopped reporting. Grey on purpose: offline is a fact to check, not an alarm.
- **Success ({colors.success})**: only for operational confirmations such as "last backup OK" on the ops side. **Online devices are not green**; they are neutral. Green everywhere would break "calm until something happens".

Light theme (embedded widgets, projection mode) uses the same token names with the values in the "Light theme" section below; it is designed and contrast-tested separately, not a mechanical inversion.

## Typography

One family in two cuts: IBM Plex Sans for everything people read, IBM Plex Mono only for identifiers and timestamps that are compared character by character (IMEI, POI numbers, event start times in lists). Plex is also what Ariane uses, so embedded widgets sit naturally inside the host page. Both are open-licensed and self-hosted.

- **Display ({typography.display})**: the counts in the security status strip and nothing else. Not for page titles.
- **Headline ({typography.headline-md})**: page and panel titles. Sentence case.
- **Body ({typography.body-md}, {typography.body-mobile} on phones)**: all running text and table cells; lines stay under 75 characters.
- **Label ({typography.label-sm})**: buttons, table headers, tab labels. Sentence case, never all caps.
- **Mono ({typography.mono})**: identifiers and timestamps only. Numbers in tables use Plex Sans with tabular figures, not mono.

## Layout

Fluid 12-column grid with {spacing.gutter} gutters, max width 1440 px. The map is the incompressible main area on Manholes and Bundles (about two thirds of the width on desktop, top half on phones); the event timeline or device list is the side panel. Spacing follows a 4 px step from {spacing.xs} to {spacing.xl}; sections are separated by {spacing.section}. On phones, a bottom tab bar (Overview / Manholes / Bundles / Plan) sits above the system gesture area; touch targets are at least 44 px. Projection mode keeps the desktop grid and steps every type size up once.

## Elevation & Depth

Flat. Depth comes from the three-step brightness ramp ({colors.neutral} → {colors.surface} → {colors.surface-raised}) and 1 px {colors.border} hairlines. The drawer is the only element that sits above the page; it uses {colors.surface-raised} and a dim scrim behind it, no drop shadow. No glows, no blurred glass.

## Shapes

Small, quiet radii: {rounded.sm} for buttons, inputs, badges; {rounded.md} for panels; {rounded.lg} is the ceiling and is used only for the sign-in panel. The drawer and the map are square ({rounded.none}) because they meet the screen edge. Nested radii never exceed their parent. No pills except the language switch.

## Components

- **Button**: primary uses {components.button-primary}, at most one per screen; hover brightens to white without moving; focus shows a 2 px outline in {colors.on-surface} offset by 2 px. Secondary uses {components.button-secondary} with a {colors.border} outline.
- **Input**: {components.input}; 44 px tall everywhere so phones and desktop share one component; errors put the message under the field in {colors.error} with an icon.
- **Panel / Table row**: panels use {components.card}; panels are never nested. Table rows are separated by hairlines, not zebra stripes; the selected row gets a 3 px left edge in {colors.on-surface} and a brighter background.
- **Status badge**: {components.status-moved}, {components.status-moving}, {components.status-offline} — always icon + word + colour. Online has no badge.
- **Map marker**: neutral filled circle (normal), amber triangle (moved in 24 h), red filled triangle (moving now), grey hollow slashed circle (offline), small "unverified" corner mark. Selection = thicker outline, not a different hue.
- **Event row**: {components.event-row}; IMEI and start time in mono, duration and flip count in Plex Sans; "Notified" slot reserved on the right.
- **Drawer**: {components.drawer}; slides in from the right on desktop, full-height bottom sheet on phones.
- **Charts (ECharts)**: neutral bars in {colors.on-surface-muted} on {colors.surface}; no gradients, no 3D; state colours are not used for categories.

## Do's and Don'ts

- Do keep the screen grey until something happens; amber and red appear only for movement, offline grey only for silence.
- Do pair every state colour with a shape and a word, in both themes.
- Do put a device or work-order ID, an event time with time zone, and an "as of" time on every block, so a screenshot explains itself.
- Do keep contrast at WCAG AA in both themes, and drop all motion under reduced-motion.
- Do show "weight pending" instead of 0, and "location unverified" next to unconfirmed manhole positions.
- Don't use neon, glows, gradients, 3D globes or scan-line effects — this is a security console, not a sci-fi HUD.
- Don't open any page on a row of big number cards; the manual demo we replace did exactly that.
- Don't use a single acid-green or red accent on near-black, indigo / purple primaries, or #0B0B0B / #111 as fake black.
- Don't use all-caps eyebrow labels, "A · B · C" metadata chains, "WORD — fragment" labels, or arrows trailing buttons.
- Don't fade-and-slide every block on load; there is one choreographed moment only (the new-event pulse).
- Don't show any Chinese text in the interface.

## Motion

```yaml
motion:
  feedback: 120ms
  content: 200ms
  pulse: 600ms
  easing: "cubic-bezier(0.2, 0, 0, 1)"
```

Motion only explains cause and effect: 120 ms for hover and press feedback, 200 ms for the drawer and row expansion, one easing curve. The single choreographed moment is the new-event pulse — the marker scales and fades three times at 600 ms each, then rests in {colors.warning}. Nothing else animates on its own. Under reduced-motion every transition is instant and the pulse is replaced by the colour and shape change alone.

## Light theme

Used by embedded widgets (default) and by projection mode. Same token names, separate values, contrast tested on their own.

```yaml
colors-light:
  primary: "#171B20"
  on-primary: "#FFFFFF"
  secondary: "#6A727D"
  neutral: "#F5F6F8"
  surface: "#FFFFFF"
  surface-raised: "#F0F2F5"
  on-surface: "#171B20"
  on-surface-muted: "#4E5661"
  border: "#D3D8DF"
  success: "#2E7D57"
  warning: "#A65A00"
  error: "#B3261E"
  offline: "#6A727D"
```

On light backgrounds amber is darkened to #A65A00 (colors-light.warning) so the "moved" state still passes AA as text; the map base layer is shown without desaturation.

## Hard constraints

| Item | Constraint |
|---|---|
| Primary | No accent hue; primary is near-white (dark) / near-black (light), only for the single primary button per screen; no purple / indigo |
| Colour count | Grey ramp plus three state colours (amber, red, grey); success only on the ops side; no gradients |
| Type | IBM Plex Sans + IBM Plex Mono only; body >= 15 px (16 px on mobile); no negative letter-spacing; type does not scale with the viewport |
| Line length and height | Running text max-width 65ch; line-height 1.4-1.6 |
| Radius | <= 8 px; graded sm / md / lg, not one radius everywhere; no card inside a card |
| Language | Interface text in English and French only |

Lint note: contrast was checked with the design.md linter (0 errors); light-theme contrast is hand-calculated and must hold in the build.

## Wireframes (ASCII, desktop)

```
┌ Ariane · Copper Watch   [Overview][Manholes][Bundles][Plan]   As of 08:42 CET  ◐  EN|FR  orange ▾ ┐
├──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ SECURITY STATUS (CMP-1)                                                                              │
│  ▲ 1  moved in last 24 h     ⊘ 2  offline     ● 9  online                       as of 08:42 CET      │
├───────────────────────────────────────────────┬──────────────────────────────────────────────────────┤
│ Latest movement events (CMP-4 ×3)             │  Map (CMP-3 compact)                                 │
│ ▲ 864317087590107  Sun 8 Nov 02:14:07 CET     │   ● ● ▲ ● ⊘ ...  12 manholes                         │
│   6 min · 9 flips · Notified —                │                                                      │
├───────────────────────────────────────────────┴──────────────────────────────────────────────────────┤
│ Copper bundles: 5 trackers · 0 online · last position Wed 14 Oct 11:43 CET          → Bundles        │
├──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Removal plan: 117 work orders · 25 with cable detail · 244.4 t planned (weight pending for 92)       │
│ Excel snapshot, as of 8 Nov 05:12 · Ariane is the source of truth                    → Plan          │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

```
┌ nav ─────────────────────────────────────────────────────────────── [24 h | 7 d | 30 d] ┐
├────────────────────────────────────────────────────────────┬────────────────────────────┤
│ Map (≈2/3)  ● normal  ▲ moved  ▲■ moving  ⊘ offline         │ Movement events (newest)   │
│  markers with "unverified" corner mark                     │ ▲ 864…0107 02:14:07 · 6 min│
│                                                            │ ▲ 864…0103 Sat 23:51 · 2 min│
│                                                            │ …                          │
└────────────────────────────────────────────────────────────┴────────────────────────────┘
                                         ┌ Drawer (CMP-6) ───────────────┐
                                         │ 864317087590107 · ▲ Moved      │
                                         │ Location unverified           │
                                         │ Volt 3.58 V · RSRP −97 dBm    │
                                         │ [7 d|30 d] line charts        │
                                         │ Events for this manhole        │
                                         └───────────────────────────────┘
```

```
Source note (CMP-10)
Filters: [UCI ▾][Subcontractor ▾][Commune ▾][Category ▾][Underground/Aerial ▾][Cable type ▾]  Clear filters
┌ Planned tonnes by subcontractor ┐ ┌ Planned tonnes by cable type ┐   (covers 25 of 117 work orders)
Work orders table (CMP-9): POI · UCI · Subcontractor · Commune · Category · Segments · km · t · Received · Planned op · OCC [Open in Ariane]
  ▸ expandable segments
SLA reference (by category) — "Reference only — not tracked per work order"
```

Bold in exactly one place: the moved manhole (amber triangle marker + amber event row edge). Motion in exactly one place: the new-event pulse (3 x 600 ms), off under reduced motion.

Output: single self-contained index.html, all CSS and JS inlined.
ZERO external dependencies — no CDN, no unpkg, no googleapis. Must work fully offline.
Cover every page and all required state variants. Use the provided real data, no Lorem ipsum.
Use only the color / type / radius / spacing tokens given above; do not invent new hex values.
Respect prefers-reduced-motion; all interactive elements keyboard-reachable with visible focus.
