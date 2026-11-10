<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { addOsmTiles } from '../osm-tiles'

// CSP probe only: a world-level view of France and one synthetic point (not a device position).
// Tiles: OpenStreetMap, same as every other map (see osm-tiles.ts).
const SYNTHETIC_CENTER: L.LatLngTuple = [46.5, 2.5]

const el = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null

onMounted(() => {
  if (!el.value) return
  map = L.map(el.value, { center: SYNTHETIC_CENTER, zoom: 5 })
  addOsmTiles(map)
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
