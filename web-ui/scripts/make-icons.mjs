#!/usr/bin/env node
// Writes the app icons into web-ui/public/icons/ (Task 11.1): a manhole cover seen from above — a light ring with a centre
// dot on the graphite background. No dependency and no external resource: pixels are drawn here (4 x 4 supersampling for
// smooth edges) and encoded as PNG with node:zlib. Re-run with `node scripts/make-icons.mjs` after changing the drawing.
// Colours are DESIGN.md tokens: background colors.neutral, mark colors.primary (no hue accent, DESIGN.md hard constraints).
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { deflateSync } from 'node:zlib'

const BG = [0x15, 0x18, 0x1c] // colors.neutral #15181C
const FG = [0xe8, 0xeb, 0xef] // colors.primary #E8EBEF
const SS = 4

// Sizes are fractions of the icon edge. "any" fills the square; "maskable" keeps the mark inside the 80 % safe circle.
const ICONS = [
  { file: 'icon-192.png', size: 192, scale: 1 },
  { file: 'icon-512.png', size: 512, scale: 1 },
  { file: 'icon-maskable-512.png', size: 512, scale: 0.72 },
  { file: 'apple-touch-icon.png', size: 180, scale: 0.86 }, // iOS rounds the corners itself; keep the ring off them
]

/** Coverage 0..1 of the mark at (x, y) in unit coordinates centred on 0. */
function mark(x, y, scale) {
  const r = Math.hypot(x, y) / scale
  const ring = r >= 0.3 && r <= 0.4
  const dot = r <= 0.1
  return ring || dot ? 1 : 0
}

function pixels(size, scale) {
  const out = Buffer.alloc(size * (size * 3 + 1))
  for (let py = 0; py < size; py++) {
    const row = py * (size * 3 + 1)
    out[row] = 0 // PNG filter type: none
    for (let px = 0; px < size; px++) {
      let hit = 0
      for (let sy = 0; sy < SS; sy++)
        for (let sx = 0; sx < SS; sx++) hit += mark((px + (sx + 0.5) / SS) / size - 0.5, (py + (sy + 0.5) / SS) / size - 0.5, scale)
      const a = hit / (SS * SS)
      for (let c = 0; c < 3; c++) out[row + 1 + px * 3 + c] = Math.round(BG[c] * (1 - a) + FG[c] * a)
    }
  }
  return out
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})
function crc32(buf) {
  let c = 0xffffffff
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}
function chunk(type, data) {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body))
  return Buffer.concat([len, body, crc])
}
function png(size, raw) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 2 // colour type: RGB, opaque (iOS fills transparency with black anyway)
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  return Buffer.concat([sig, chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))])
}

const outDir = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'icons')
mkdirSync(outDir, { recursive: true })
for (const icon of ICONS) {
  const file = resolve(outDir, icon.file)
  const data = png(icon.size, pixels(icon.size, icon.scale))
  writeFileSync(file, data)
  console.log(`make-icons: ${icon.file} ${icon.size}x${icon.size} ${data.length} bytes`)
}
