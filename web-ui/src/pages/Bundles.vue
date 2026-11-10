<script setup lang="ts">
// SCREEN-3: GPS trackers on a map (last position) with a device list beside / below it; picking a tracker draws its 7-day
// track. The selected tracker lives in the URL (?device=…). Position and track only: no trip status, no copper bundle number
// (the tracker-to-bundle mapping has no ledger, Architecture §9). Refreshes with the shared 60 s live tick.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BundleMap from '../components/BundleMap.vue'
import DeviceList from '../components/DeviceList.vue'
import { ApiError } from '../api'
import { clock, dateTime } from '../format'
import { t, tf, tp } from '../i18n'
import { live, refresh, useLive } from '../live'
import { getBundles, getTrack } from '../resources'
import type { Bundle, TrackPoint } from '../resources'

const route = useRoute()
const router = useRouter()
const device = computed(() => (typeof route.query.device === 'string' && route.query.device ? route.query.device : null))

const bundles = ref<Bundle[]>([])
const asOf = ref<string | null>(null)
const loaded = ref(false)
const failed = ref(false)
const track = ref<TrackPoint[]>([])
const trackState = ref<'idle' | 'loading' | 'ready' | 'failed'>('idle')
let bundlesReq = 0
let trackReq = 0

async function loadBundles(): Promise<void> {
  const mine = ++bundlesReq
  try {
    const r = await getBundles()
    if (mine !== bundlesReq) return
    bundles.value = r.items
    asOf.value = r.asOf
    loaded.value = true
    failed.value = false
  } catch (e) {
    if (mine !== bundlesReq || (e instanceof ApiError && e.status === 401)) return
    failed.value = true // the data on screen stays as it was
    console.error('trackers load failed', e)
  }
}

async function loadTrack(quiet = false): Promise<void> {
  const id = device.value
  const mine = ++trackReq
  if (!id) {
    track.value = []
    trackState.value = 'idle'
    return
  }
  if (!quiet) {
    track.value = []
    trackState.value = 'loading'
  }
  try {
    const points = await getTrack(id, 7)
    if (mine !== trackReq) return
    track.value = points
    trackState.value = 'ready'
  } catch (e) {
    if (mine !== trackReq || (e instanceof ApiError && e.status === 401)) return
    if (!quiet) trackState.value = 'failed' // a failed background refresh keeps the track on screen
    console.error('track load failed', e)
  }
}

let stop: (() => void) | null = null
onMounted(() => {
  stop = useLive() // banner state (collector delay, offline) and the 60 s tick
  void loadBundles()
  void loadTrack()
})
onBeforeUnmount(() => stop?.())
watch(device, () => void loadTrack())
watch(() => live.tick, () => {
  void loadBundles()
  void loadTrack(true)
})

function select(id: string): void {
  const query = { ...route.query }
  if (device.value === id) delete query.device // a second click hides the track
  else query.device = id
  void router.replace({ query })
}

function hide(): void {
  const query = { ...route.query }
  delete query.device
  void router.replace({ query })
}

function reload(): void {
  void loadBundles()
  void refresh()
}

const unlocated = computed(() => bundles.value.filter((b) => b.lat === null || b.lon === null).length)
const selectedWho = computed(() => {
  const b = bundles.value.find((x) => x.device_id === device.value)
  return b?.name || device.value || ''
})
/** Trackers exist but none reported within 24 h (production today): say so and give the newest report time. */
const silent24 = computed(() => bundles.value.length > 0 && !bundles.value.some((b) => b.online))
const lastReport = computed(() => {
  const times = bundles.value.map((b) => b.at).filter((a): a is string => !!a)
  return times.length ? times.reduce((a, b) => (Date.parse(a) >= Date.parse(b) ? a : b)) : null
})
</script>

<template>
  <section class="bundles">
    <div class="heading">
      <h1 tabindex="-1">{{ t('bundles') }}</h1>
      <span v-if="loaded && asOf" class="small muted">{{ tp('trackercount1', 'trackercount', bundles.length) }}, {{ t('asof') }} {{ clock(asOf) }}</span>
    </div>
    <p class="note" data-testid="bundles-note">{{ t('bundlesnote') }}</p>
    <Banner />
    <div v-if="failed && !live.error" class="failed" role="alert" data-testid="bundles-error">
      <span>{{ t('bundlesfailed') }}</span>
      <button type="button" @click="reload">{{ t('reload') }}</button>
    </div>
    <div v-if="silent24" class="silent" role="status" data-testid="no-position-24h">
      <strong>{{ t('nopos24') }}</strong>
      <span v-if="lastReport">{{ tf('lastpositionat', { t: dateTime(lastReport, true) }) }}</span>
    </div>

    <p v-if="loaded && !bundles.length" class="panel empty" data-testid="bundles-empty">{{ t('notrackers') }}</p>
    <div v-else class="split">
      <section class="panel">
        <div class="panel-head">
          <h2>{{ t('bundlesmap') }}</h2>
          <span v-if="unlocated" class="small muted">{{ tf('nolocation', { n: unlocated }) }}</span>
        </div>
        <div v-if="!loaded" class="skeleton map" aria-busy="true" :aria-label="t('loadingState')"></div>
        <BundleMap v-else :bundles="bundles" :selected="device" :track="track" @select="select" />
        <div v-if="device" class="track-status small" aria-live="polite" data-testid="track-status">
          <span v-if="trackState === 'loading'" aria-busy="true">{{ t('loadingState') }}</span>
          <span v-else-if="trackState === 'failed'" class="err" role="alert">{{ t('trackfailed') }}</span>
          <span v-else-if="trackState === 'ready' && !track.length">{{ t('tracknone') }}</span>
          <span v-else-if="trackState === 'ready'">{{ tf('trackof', { who: selectedWho }) }} · {{ tp('trackpoints1', 'trackpoints', track.length) }}</span>
          <button type="button" @click="hide">{{ t('hidetrack') }}</button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>{{ t('bundlelist') }}</h2>
          <span class="small muted">{{ tp('trackercount1', 'trackercount', bundles.length) }}</span>
        </div>
        <div v-if="!loaded" class="skeleton rows" aria-busy="true" :aria-label="t('loadingState')"></div>
        <DeviceList v-else :bundles="bundles" :selected="device" @select="select" />
      </section>
    </div>
  </section>
</template>

<style scoped>
.heading {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}
.note {
  margin: 0 0 var(--space-lg);
  padding: var(--space-md) var(--space-lg);
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
}
.failed,
.silent {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
  padding: var(--space-md) var(--space-lg);
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
}
.failed {
  color: var(--color-error);
  border-color: var(--color-error);
}
.failed button {
  margin-left: auto;
  color: inherit;
}
.split {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
  gap: var(--space-lg);
  align-items: start;
}
.panel {
  min-width: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  overflow: hidden;
}
.panel-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-lg);
  border-bottom: 1px solid var(--color-border);
}
.panel-head h2 {
  font-size: var(--type-body-size);
}
.empty {
  padding: var(--space-section) var(--space-lg);
}
.track-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md) var(--space-lg);
  border-top: 1px solid var(--color-border);
}
.track-status button {
  margin-left: auto;
}
.err {
  color: var(--color-error);
}
.muted {
  color: var(--color-on-surface-muted);
}
.skeleton {
  background: var(--color-surface-raised);
}
.skeleton.map {
  height: 520px;
}
.skeleton.rows {
  height: 240px;
  margin: var(--space-lg);
  border-radius: var(--radius-sm);
}
@media (max-width: 800px) {
  .split {
    grid-template-columns: 1fr;
  }
}
</style>
