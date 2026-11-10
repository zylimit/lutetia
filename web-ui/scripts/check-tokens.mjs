#!/usr/bin/env node
// Fails (exit 1) when web-ui/src holds a hex colour (#rgb, #rgba, #rrggbb, #rrggbbaa) that DESIGN.md's colour tables do not list.
// DESIGN.md is the only colour source: the allowed set is every hex in its front matter (colors:, components:) and in its
// "Light theme" yaml block (colors-light:). Hexes that only appear in prose (for example the forbidden #0B0B0B) are not allowed.
// Exit codes: 0 clean, 1 offending colour found, 2 the script could not do its job (DESIGN.md or src missing / unreadable).
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HEX = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_-])/g
const SCANNED = new Set(['.vue', '.ts', '.tsx', '.js', '.mjs', '.css', '.html', '.svg', '.json'])

const NAMED = new Set(
  'aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen'.split(' '),
)
// Other ways to write a colour outside the tokens: rgb()/rgba()/hsl()/hsla(), and a CSS named colour (red, blue, ...) used as the value
// of a colour property (declaration `color: red` or attribute fill="red"). transparent / currentColor / inherit / initial / unset are not colours.
const COLOR_FN = /(?<![\w-])(?:rgba?|hsla?)\(/gi
const COLOR_PROP = '(?:color|background(?:-color)?|border(?:-(?:top|right|bottom|left|block|inline)(?:-color)?|-color)?|outline(?:-color)?|fill|stroke|caret-color|accent-color|text-decoration-color|box-shadow|text-shadow)'
const NAMED_DECL = new RegExp(`(?<![\\w-])${COLOR_PROP}\\s*:\\s*([^;{}]+)`, 'gi')
const NAMED_ATTR = new RegExp(`(?<![\\w:-])${COLOR_PROP}\\s*=\\s*["']([^"']+)["']`, 'gi')

/** Colour words of a property value, with var(...), url(...) and strings blanked first. */
function namedIn(value) {
  const bare = value.replace(/var\([^)]*\)|url\([^)]*\)|"[^"]*"|'[^']*'/gi, ' ')
  return (bare.match(/[a-z]+/gi) ?? []).filter((w) => NAMED.has(w.toLowerCase()))
}

/** Offending { line, hex } for rgb()/hsl() functions and named colours (tokens.css is exempt: the caller skips it). */
export function otherColors(text) {
  const out = []
  text.split(/\r?\n/).forEach((line, i) => {
    for (const m of line.matchAll(COLOR_FN)) out.push({ line: i + 1, hex: m[0] })
    for (const re of [NAMED_DECL, NAMED_ATTR]) for (const m of line.matchAll(re)) for (const w of namedIn(m[1])) out.push({ line: i + 1, hex: w })
  })
  return out
}

const here = dirname(fileURLToPath(import.meta.url))
const srcDir = resolve(here, '..', 'src')
const tokensFile = resolve(srcDir, 'styles', 'tokens.css')
const designFile = resolve(here, '..', '..', 'DESIGN.md')

function fail(msg) {
  console.error(`check-tokens: ${msg}`)
  process.exit(2)
}

/** The hexes DESIGN.md allows: front matter plus the fenced yaml block that starts with `colors-light:`. */
export function allowedColors(markdown) {
  const lines = markdown.split(/\r?\n/)
  if (lines[0].trim() !== '---') throw new Error('DESIGN.md has no front matter')
  const end = lines.indexOf('---', 1)
  if (end < 0) throw new Error('DESIGN.md front matter is not closed')
  let scope = lines.slice(1, end).join('\n')
  const light = markdown.match(/```yaml\s*\n(colors-light:[\s\S]*?)```/)
  if (!light) throw new Error('DESIGN.md has no colors-light yaml block')
  scope += '\n' + light[1]
  const found = new Set((scope.match(HEX) ?? []).map((h) => h.toUpperCase()))
  if (found.size < 15) throw new Error(`only ${found.size} colours read from DESIGN.md, expected the full tables`)
  return found
}

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* walk(p)
    else if (SCANNED.has(name.slice(name.lastIndexOf('.')))) yield p
  }
}

/** Offending { file, line, hex } in one file's text. */
export function offenders(text, allowed) {
  const out = []
  text.split(/\r?\n/).forEach((line, i) => {
    for (const m of line.matchAll(HEX)) if (!allowed.has(m[0].toUpperCase())) out.push({ line: i + 1, hex: m[0] })
  })
  return out
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let allowed
  try {
    allowed = allowedColors(readFileSync(designFile, 'utf8'))
  } catch (e) {
    fail(`cannot read the colour tables of ${designFile}: ${e.message}`)
  }
  let files
  try {
    files = [...walk(srcDir)]
  } catch (e) {
    fail(`cannot scan ${srcDir}: ${e.message}`)
  }
  const bad = files.flatMap((f) => {
    const text = readFileSync(f, 'utf8')
    const found = [...offenders(text, allowed), ...(f === tokensFile ? [] : otherColors(text))]
    return found.map((o) => ({ file: relative(resolve(here, '..'), f), ...o }))
  })
  for (const b of bad) console.error(`${b.file}:${b.line}: ${b.hex} is not a colour from the DESIGN.md tables / var(--color-…) tokens`)
  if (bad.length) {
    console.error(`check-tokens: ${bad.length} colour(s) outside DESIGN.md. Use a var(--color-…) token or update DESIGN.md first.`)
    process.exit(1)
  }
  console.log(`check-tokens: ok, ${files.length} files scanned, ${allowed.size} DESIGN.md colours allowed`)
}
