<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'

// CSP probe only: a world-level view of France and one synthetic point (not a device position).
// Tiles: Google test-phase layer, same as lutetia/web/static/map.js (progress Decisions 2026-11-07, revoked by #88 / Task 13.2).
const SYNTHETIC_CENTER: L.LatLngTuple = [46.5, 2.5]

const el = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null

onMounted(() => {
  if (!el.value) return
  map = L.map(el.value, { center: SYNTHETIC_CENTER, zoom: 5 })
  L.tileLayer('https://mt{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', {
    subdomains: '0123',
    attribution: '© Google',
    maxZoom: 20,
  }).addTo(map)
  L.circleMarker(SYNTHETIC_CENTER, { radius: 6 }).addTo(map)
})

onBeforeUnmount(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="el" class="probe-map" data-testid="probe-map"></div>
</template>

<style scoped>
.probe-map {
  height: 320px;
  width: 100%;
}
</style>
