<script setup lang="ts">
// CMP-3 on SCREEN-3: Leaflet map of the GPS trackers' last positions plus the 7-day track of the selected one (polyline,
// start and end marks). Trackers only show online (filled circle) or offline (hollow slashed circle): trip status is not
// computed (Spec #96), so no "moving" shape here. Markers are kept per device so keyboard focus survives the 60 s refresh.
// Styles of the base map and the marker shapes are the ones of ManholeMap (.mh-map / .mh-marker in its global style block).
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { dateTime } from '../format'
import { t } from '../i18n'
import type { Bundle, TrackPoint } from '../resources'
import { markerSvg } from './marker-svg'

const props = defineProps<{ bundles: Bundle[]; selected: string | null; track: TrackPoint[] }>()
const emit = defineEmits<{ select: [id: string, el: HTMLElement] }>()

const FRANCE: L.LatLngTuple = [46.5, 2.5] // starting view before any marker exists (not a device position)
const el = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let fitted = false
let trackLayer: L.LayerGroup | null = null
const markers = new Map<string, { marker: L.Marker; online: boolean }>()

function label(b: Bundle): string {
  const when = b.at ? `, ${dateTime(b.at, true)}` : ''
  return `${b.name || b.device_id}, ${t(b.online ? 'online' : 'offline')}${when}`
}

function sync(): void {
  if (!map) return
  const seen = new Set<string>()
  for (const b of props.bundles) {
    if (b.lat === null || b.lon === null) continue
    seen.add(b.device_id)
    let entry = markers.get(b.device_id)
    if (!entry || entry.online !== b.online) {
      entry?.marker.remove()
      const icon = L.divIcon({ className: 'mh-marker', html: markerSvg(b.online ? 'quiet' : 'offline', false), iconSize: [32, 32], iconAnchor: [16, 16] })
      const marker = L.marker([b.lat, b.lon], { icon, keyboard: true, title: label(b) }).addTo(map)
      const id = b.device_id
      marker.on('click', () => emit('select', id, marker.getElement() as HTMLElement))
      entry = { marker, online: b.online }
      markers.set(id, entry)
    } else {
      entry.marker.setLatLng([b.lat, b.lon])
    }
    const node = entry.marker.getElement()
    if (node) {
      node.dataset.device = b.device_id
      node.dataset.kind = b.online ? 'quiet' : 'offline'
      node.setAttribute('aria-label', label(b))
      node.classList.toggle('selected', props.selected === b.device_id)
    }
  }
  for (const [id, entry] of markers) {
    if (!seen.has(id)) {
      entry.marker.remove()
      markers.delete(id)
    }
  }
  if (!fitted && markers.size && !props.selected) {
    map.fitBounds(L.latLngBounds([...markers.values()].map((e) => e.marker.getLatLng())), { padding: [32, 32], maxZoom: 16 })
    fitted = true
  }
}

function endMark(kind: 'start' | 'end', p: TrackPoint): L.Marker {
  const shape = kind === 'start' ? '<rect class="mark" x="4" y="4" width="12" height="12"/>' : '<circle class="mark" cx="10" cy="10" r="6"/><circle class="dot" cx="10" cy="10" r="2"/>'
  const icon = L.divIcon({ className: `trk-end ${kind}`, html: `<svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">${shape}</svg>`, iconSize: [20, 20], iconAnchor: [10, 10] })
  const text = `${t(kind === 'start' ? 'trackstart' : 'trackend')}, ${dateTime(p.at, true)}`
  return L.marker([p.lat, p.lon], { icon, title: text, keyboard: false, zIndexOffset: 500 }).bindTooltip(text)
}

function drawTrack(): void {
  if (!map) return
  trackLayer?.remove()
  trackLayer = null
  if (!props.track.length) return
  const pts = props.track
  const line = L.polyline(pts.map((p) => [p.lat, p.lon] as L.LatLngTuple), { className: 'trk-line', weight: 3, interactive: false })
  trackLayer = L.layerGroup([line, endMark('start', pts[0]), endMark('end', pts[pts.length - 1])]).addTo(map)
  map.fitBounds(line.getBounds(), { padding: [48, 48], maxZoom: 16 })
}

function focusSelected(): void {
  const entry = props.selected ? markers.get(props.selected) : undefined
  if (map && entry && !props.track.length) map.panTo(entry.marker.getLatLng())
}

onMounted(() => {
  if (!el.value) return
  map = L.map(el.value, { center: FRANCE, zoom: 5 })
  // Test-phase tiles, same as ManholeMap (Decisions 2026-11-07; replaced by #88 / Task 13.2).
  L.tileLayer('https://mt{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', { subdomains: '0123', attribution: '© Google', maxZoom: 20 }).addTo(map)
  sync()
  drawTrack()
  focusSelected()
})

watch(() => [props.bundles, props.selected], sync, { deep: true })
watch(() => props.track, drawTrack)
watch(() => props.selected, focusSelected)

onBeforeUnmount(() => {
  map?.remove()
  map = null
  trackLayer = null
  markers.clear()
})
</script>

<template>
  <div ref="el" class="mh-map bundle-map" role="region" :aria-label="t('bundlesmap')" data-testid="bundle-map"></div>
</template>

<style>
/* Not scoped: Leaflet builds these elements itself. */
.trk-line {
  fill: none;
  stroke: var(--color-on-surface);
  stroke-width: 3;
  stroke-linejoin: round;
}
.trk-end svg {
  display: block;
}
.trk-end .mark {
  fill: var(--color-surface);
  stroke: var(--color-on-surface);
  stroke-width: 2.5;
}
.trk-end .dot {
  fill: var(--color-on-surface);
}
</style>
