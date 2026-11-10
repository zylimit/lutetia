// Base map of every Leaflet map in the project dashboard and the widgets: OpenStreetMap standard tiles (Task 13.2, #88).
// The site-wide Referrer-Policy is same-origin, which OSM's tile servers refuse (no Referer); each tile <img> sets its own policy.
import * as L from 'leaflet'

export const OSM_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
export const OSM_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'

export function addOsmTiles(map: L.Map): L.TileLayer {
  return L.tileLayer(OSM_TILE_URL, {
    maxZoom: 19,
    referrerPolicy: 'strict-origin-when-cross-origin',
    attribution: OSM_ATTRIBUTION,
  }).addTo(map)
}
