<script setup lang="ts">
// CMP-3: Leaflet map of the manholes. Shape + colour double coding (DESIGN.md Components "Map marker"): quiet filled circle,
// moved amber triangle, moving red filled triangle, offline grey hollow slashed circle, offline with an unfinished event
// = offline marker plus a red alert triangle (Decisions 2026-11-10), inactive = small grey dot (not in Design-Brief: Task 9.3
// assumption). Every marker carries the "unverified" corner mark: no position is verified yet (location_verified false).
// Markers are kept per device and only their classes change on refresh, so keyboard focus survives the 60 s refresh.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { t } from '../i18n'
import { addOsmTiles } from '../osm-tiles'
import type { Manhole } from '../resources'
import { markerKind, markerSvg } from './marker-svg'

const props = defineProps<{ manholes: Manhole[]; selected?: string | null; pulse?: string[]; compact?: boolean }>()
const emit = defineEmits<{ select: [id: string, el: HTMLElement] }>()

// Starting view before any marker exists: metropolitan France at country zoom (not a device position).
const FRANCE: L.LatLngTuple = [46.5, 2.5]
const el = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let fitted = false
const markers = new Map<string, { marker: L.Marker; kind: string }>()

function label(m: Manhole, kind: string): string {
  const state = t(kind === 'suspicious' ? 'suspicious' : (kind as 'quiet'))
  return `${m.name || m.device_id}, ${state}${m.location_verified ? '' : `, ${t('location')}`}`
}

function sync(): void {
  if (!map) return
  const seen = new Set<string>()
  for (const m of props.manholes) {
    if (m.lat === null || m.lon === null) continue
    seen.add(m.device_id)
    const kind = markerKind(m)
    let entry = markers.get(m.device_id)
    if (!entry || entry.kind !== kind) {
      entry?.marker.remove()
      const icon = L.divIcon({ className: 'mh-marker', html: markerSvg(kind, !m.location_verified), iconSize: [32, 32], iconAnchor: [16, 16] })
      const marker = L.marker([m.lat, m.lon], { icon, keyboard: true, title: label(m, kind) }).addTo(map)
      const id = m.device_id
      marker.on('click', () => emit('select', id, marker.getElement() as HTMLElement)) // Leaflet turns Enter on a focused marker into click
      entry = { marker, kind }
      markers.set(id, entry)
    } else {
      entry.marker.setLatLng([m.lat, m.lon])
    }
    const node = entry.marker.getElement()
    if (node) {
      node.dataset.device = m.device_id
      node.dataset.kind = kind
      node.setAttribute('aria-label', label(m, kind))
      node.classList.toggle('selected', props.selected === m.device_id)
      node.classList.toggle('pulse', !!props.pulse?.includes(m.device_id))
    }
  }
  for (const [id, entry] of markers) {
    if (!seen.has(id)) {
      entry.marker.remove()
      markers.delete(id)
    }
  }
  if (!fitted && markers.size) {
    map.fitBounds(L.latLngBounds([...markers.values()].map((e) => e.marker.getLatLng())), { padding: [32, 32], maxZoom: 16 })
    fitted = true
  }
}

function focusSelected(): void {
  const entry = props.selected ? markers.get(props.selected) : undefined
  if (map && entry) map.panTo(entry.marker.getLatLng())
}

onMounted(() => {
  if (!el.value) return
  map = L.map(el.value, { center: FRANCE, zoom: 5, scrollWheelZoom: !props.compact })
  addOsmTiles(map)
  sync()
  focusSelected()
})

watch(() => [props.manholes, props.selected, props.pulse], sync, { deep: true })
watch(() => props.selected, focusSelected)

onBeforeUnmount(() => {
  map?.remove()
  map = null
  markers.clear()
})
</script>

<template>
  <div ref="el" class="mh-map" :class="{ compact }" role="region" :aria-label="t('map')" data-testid="manhole-map"></div>
</template>

<style>
/* Not scoped: Leaflet creates the marker elements, they carry no scope attribute. */
.mh-map {
  width: 100%;
  height: 520px;
  background: var(--color-neutral);
}
.mh-map.compact {
  height: 360px;
}
[data-theme='dark'] .mh-map .leaflet-tile-pane {
  filter: grayscale(0.8) brightness(0.7) contrast(1.1); /* Design-Brief CMP-3: desaturated base map in the dark theme */
}
.mh-map .leaflet-control-attribution {
  background: var(--color-surface);
  color: var(--color-on-surface-muted);
}
.mh-map .leaflet-control-attribution a {
  color: var(--color-on-surface-muted);
}
.mh-marker {
  background: transparent;
  border: 0;
  cursor: pointer;
}
.mh-marker svg {
  display: block;
  overflow: visible;
}
.mh-marker .shape {
  fill: var(--color-on-surface-muted);
  stroke: var(--color-neutral);
  stroke-width: 2;
}
.mh-marker[data-kind='moved'] .shape {
  fill: var(--color-warning);
}
.mh-marker[data-kind='moving'] .shape {
  fill: var(--color-error);
}
.mh-marker[data-kind='offline'] .shape,
.mh-marker[data-kind='suspicious'] .shape {
  fill: var(--color-neutral);
  stroke: var(--color-offline);
  stroke-width: 3;
}
.mh-marker .slash {
  stroke: var(--color-offline);
  stroke-width: 3;
}
.mh-marker .alert {
  fill: var(--color-error);
  stroke: var(--color-neutral);
  stroke-width: 1.5;
}
.mh-marker[data-kind='inactive'] .shape {
  fill: var(--color-offline);
  stroke-width: 1;
}
.mh-marker .unverified {
  fill: var(--color-surface);
  stroke: var(--color-on-surface-muted);
  stroke-width: 1;
}
.mh-marker:hover .shape {
  stroke: var(--color-on-surface);
}
.mh-marker.selected .shape,
.mh-marker:focus-visible .shape {
  stroke: var(--color-on-surface);
  stroke-width: 4;
}
.mh-marker:focus-visible {
  outline: 2px solid var(--color-on-surface);
  outline-offset: 2px;
}
/* DESIGN.md Motion: the one choreographed moment. base.css turns every animation off under reduced motion, and live.ts
   does not add the class at all then. */
.mh-marker.pulse .shape {
  transform-box: fill-box;
  transform-origin: center;
  animation: mh-pulse var(--motion-pulse) var(--motion-easing) 3;
}
@keyframes mh-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.6);
    opacity: 0.4;
  }
}
@media (max-width: 800px) {
  .mh-map,
  .mh-map.compact {
    height: 50vh;
    min-height: 280px;
  }
}
</style>
