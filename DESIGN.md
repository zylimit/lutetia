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

## 硬约束

| 项 | 约束 |
|---|---|
| 主色 | 无色相强调；primary 为近白（深色）/ 近黑（浅色），只给每屏唯一主按钮；不用紫 / 靛 |
| 色彩数量 | 灰阶 + 三个状态色（琥珀、红、灰），success 只在运维侧；无渐变 |
| 字体 | IBM Plex Sans + IBM Plex Mono（同一家族两种）；正文 ≥ 15 px（手机 16 px）；letter-spacing 不为负；字号不随视口缩放 |
| 行长与行高 | 正文 `max-width: 65ch`；`line-height` 1.4–1.6 |
| 圆角 | ≤ 8 px；按 sm / md / lg 分级，不全场一个圆角；禁卡中卡 |
| 语言 | 界面只用英文与法语 |

2026-11-08 `npx @google/design.md lint`：0 error；已修 1 条对比度（离线徽章文字 3.97:1 → 改用 on-surface-muted）；余下 warning 为「token 只在正文用、未被组件引用」4 条与「motion / colors-light 非标准段、导出时忽略」2 条，有意保留。浅色主题与 {colors.offline} 作图标时的对比未被 lint 覆盖，为手算估计，实现时复测。
