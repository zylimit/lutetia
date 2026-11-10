<script setup lang="ts">
// SCREEN-2: map (about 2/3) + movement timeline (1/3). Range, status filter and the open manhole live in the URL
// (?range=7d&status=moved&device=…), so back / forward and a shared link restore the view (Design-Brief 5.1).
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import EventRow from '../components/EventRow.vue'
import ManholeDrawer from '../components/ManholeDrawer.vue'
import ManholeList from '../components/ManholeList.vue'
import ManholeMap from '../components/ManholeMap.vue'
import MapLegend from '../components/MapLegend.vue'
import RangeSwitch from '../components/RangeSwitch.vue'
import { ApiError } from '../api'
import { clock } from '../format'
import { t, tf, tp } from '../i18n'
import type { Key } from '../i18n'
import { byId, isSuspicious, live, useLive } from '../live'
import { eventKey, getEventsSince } from '../resources'
import type { FallEvent } from '../resources'
import { parseRange, RANGE_HOURS } from '../range'
import type { Range } from '../range'

const FILTERS: Record<string, { statuses: string[]; label: Key }> = {
  moved: { statuses: ['moved', 'moving'], label: 'moved24' },
  offline: { statuses: ['offline'], label: 'offline' },
  quiet: { statuses: ['quiet'], label: 'online' },
  inactive: { statuses: ['inactive'], label: 'inactive' },
}
const EMPTY: Record<Range, Key> = { '24h': 'noevents24', '7d': 'noevents', '30d': 'noevents30' }

const route = useRoute()
const router = useRouter()
const range = computed(() => parseRange(route.query.range))
const status = computed(() => (typeof route.query.status === 'string' && route.query.status in FILTERS ? route.query.status : null))
const device = computed(() => (typeof route.query.device === 'string' && route.query.device ? route.query.device : null))

const events = ref<FallEvent[]>([])
const eventsLoaded = ref(false)
const eventsFailed = ref(false)
let request = 0
let trigger: HTMLElement | null = null

async function loadEvents(): Promise<void> {
  const mine = ++request
  try {
    const list = await getEventsSince(RANGE_HOURS[range.value])
    if (mine !== request) return
    events.value = list
    eventsLoaded.value = true
    eventsFailed.value = false
  } catch (e) {
    if (mine !== request || (e instanceof ApiError && e.status === 401)) return
    eventsFailed.value = true // the list on screen stays as it was
    console.error('movement events load failed', e)
  }
}

let stop: (() => void) | null = null
onMounted(() => {
  stop = useLive()
  void loadEvents()
})
let unmounted = false
let pendingDone: (() => void) | null = null // the timeline wait of drawerClosed, released when the page goes away
onBeforeUnmount(() => {
  unmounted = true
  pendingDone?.()
  stop?.()
})
watch(range, () => {
  eventsLoaded.value = false
  void loadEvents()
})
watch(() => live.tick, () => void loadEvents())

const shown = computed(() => {
  const f = status.value ? FILTERS[status.value].statuses : null
  return f ? live.manholes.filter((m) => f.includes(m.status)) : live.manholes
})
const shownIds = computed(() => new Set(shown.value.map((m) => m.device_id)))
const unlocated = computed(() => shown.value.filter((m) => m.lat === null || m.lon === null).length)

/** Newest first, except an unfinished event of a manhole that is now offline: pinned on top (Decisions 2026-11-10). */
const timeline = computed(() => {
  const list = status.value ? events.value.filter((e) => shownIds.value.has(e.device_id)) : events.value
  const suspicious = (e: FallEvent) => isSuspicious(e, byId(e.device_id)?.status)
  return [...list.filter(suspicious), ...list.filter((e) => !suspicious(e))]
})

function setQuery(patch: Record<string, string | null>): void {
  const query = { ...route.query, ...patch }
  for (const k of Object.keys(query)) if (query[k] === null || query[k] === undefined) delete query[k]
  void router.replace({ query })
}

function select(id: string, el: HTMLElement): void {
  trigger = el
  void router.push({ query: { ...route.query, device: id } })
}

async function drawerClosed(): Promise<void> {
  const id = device.value
  if (id) setQuery({ device: null })
  await nextTick()
  // The element that opened the drawer; when the page was opened with ?device= (from Overview) there is none: the event
  // bar of that manhole in the timeline first, then its marker, then the page heading.
  const find = (sel: string) => (id ? document.querySelector<HTMLElement>(`${sel}[data-device="${CSS.escape(id)}"]`) : null)
  const opener = trigger?.isConnected ? trigger : null
  trigger = null
  if (!opener && id && !find('.timeline .event')) await timelineRendered() // Esc before the timeline arrived: wait for it
  if (unmounted) return // the page was left meanwhile: nothing here to focus
  const back = opener ?? find('.timeline .event') ?? find('.mh-marker') ?? document.querySelector<HTMLElement>('main h1')
  back?.focus()
}

const TIMELINE_WAIT_MS = 2000
/** Resolves after the next render of the timeline, or after 2 s (then the marker takes the focus). */
function timelineRendered(): Promise<void> {
  if (eventsLoaded.value) return Promise.resolve() // already loaded: this device simply has no event bar
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => done(), TIMELINE_WAIT_MS)
    const unwatch = watch(timeline, () => done(), { flush: 'post' })
    function done(): void {
      window.clearTimeout(timer)
      unwatch()
      pendingDone = null
      resolve()
    }
    pendingDone = done
  })
}

/** CMP-4 keyboard: up / down move between rows of the timeline, Enter opens (the rows are buttons). */
function arrows(ev: KeyboardEvent): void {
  if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return
  const rows = Array.from((ev.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('.event'))
  const at = rows.indexOf(document.activeElement as HTMLElement)
  if (at < 0) return
  ev.preventDefault()
  rows[Math.min(rows.length - 1, Math.max(0, at + (ev.key === 'ArrowDown' ? 1 : -1)))]?.focus()
}
</script>

<template>
  <section class="manholes">
    <div class="heading">
      <h1 tabindex="-1">{{ t('manholes') }}</h1>
      <span v-if="live.asOf" class="small muted">{{ tp('manholecount1', 'manholecount', live.summary?.manholes.all ?? 0) }}, {{ t('asof') }} {{ clock(live.asOf) }}</span>
    </div>
    <Banner />
    <div class="toolbar">
      <RangeSwitch :model-value="range" @update:model-value="(r) => setQuery({ range: r })" />
      <button v-if="status" type="button" :aria-label="`${t('clearfilter')}: ${t(FILTERS[status].label)}`" @click="setQuery({ status: null })">
        {{ t(FILTERS[status].label) }} ×
      </button>
    </div>

    <div class="split">
      <div class="left">
      <section class="panel">
        <div class="panel-head">
          <h2>{{ t('map') }}</h2>
          <span v-if="unlocated" class="small muted">{{ tf('nolocation', { n: unlocated }) }}</span>
        </div>
        <div v-if="!live.loaded" class="skeleton map" aria-busy="true" :aria-label="t('loadingState')"></div>
        <ManholeMap v-else :manholes="shown" :selected="device" :pulse="live.pulse" @select="select" />
        <MapLegend />
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>{{ t('manholelist') }}</h2>
          <span class="small muted">{{ tp('manholecount1', 'manholecount', shown.length) }}</span>
        </div>
        <ManholeList :manholes="shown" :selected="device" @select="select" />
      </section>
      </div>

      <section class="panel">
        <div class="panel-head">
          <h2>{{ t('events') }}</h2>
          <span class="small muted">{{ t('sort') }}</span>
        </div>
        <p v-if="eventsFailed" class="small failed" role="alert">{{ t('errorbanner') }}</p>
        <div class="timeline" role="list" :aria-label="t('events')" @keydown="arrows">
          <div v-if="!eventsLoaded && !eventsFailed" class="skeleton rows" aria-busy="true" :aria-label="t('loadingState')"></div>
          <p v-else-if="eventsLoaded && !timeline.length" class="empty muted">{{ t(status ? 'nomovement' : EMPTY[range]) }}</p>
          <div v-for="e in timeline" :key="eventKey(e)" role="listitem">
            <EventRow :event="e" :device-status="byId(e.device_id)?.status" :selected="device === e.device_id" @click="select(e.device_id, $event.currentTarget as HTMLElement)" />
          </div>
        </div>
        <div v-if="live.asOf" class="panel-foot small muted">{{ t('asof') }} {{ clock(live.asOf) }}</div>
      </section>
    </div>
    <ManholeDrawer :device-id="device" @closed="drawerClosed" />
  </section>
</template>

<style scoped>
.heading {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
}
.split {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
  gap: var(--space-lg);
  align-items: start;
}
.left {
  display: grid;
  gap: var(--space-lg);
  min-width: 0;
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
.panel-foot {
  padding: var(--space-md) var(--space-lg);
  border-top: 1px solid var(--color-border);
}
.timeline {
  max-height: 620px;
  overflow: auto;
}
.empty {
  padding: var(--space-section) var(--space-lg);
}
.failed {
  padding: var(--space-md) var(--space-lg);
  color: var(--color-error);
}
.skeleton {
  background: var(--color-surface-raised);
}
.skeleton.map {
  height: 520px;
}
.skeleton.rows {
  height: 320px;
  margin: var(--space-lg);
  border-radius: var(--radius-sm);
}
@media (max-width: 800px) {
  .split {
    grid-template-columns: 1fr;
  }
  .timeline {
    max-height: none;
  }
}
</style>
