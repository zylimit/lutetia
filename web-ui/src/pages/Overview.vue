<script setup lang="ts">
// SCREEN-1: security first (status strip, latest three movement events, map), then one line each for bundles and the plan.
// FLOW-4: the Monday-morning check — what moved, and one click to its detail on the Manholes page.
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import EventRow from '../components/EventRow.vue'
import ManholeMap from '../components/ManholeMap.vue'
import MapLegend from '../components/MapLegend.vue'
import StatusStrip from '../components/StatusStrip.vue'
import { clock, dateTime, num } from '../format'
import { t, tf, tp } from '../i18n'
import { byId, live, useLive } from '../live'
import { eventKey } from '../resources'
import type { FallEvent } from '../resources'
import type { Range } from '../range'

const router = useRouter()
let stop: (() => void) | null = null
onMounted(() => (stop = useLive()))
onBeforeUnmount(() => stop?.())

const counts = computed(() => live.summary?.manholes ?? null)
const empty = computed(() => counts.value !== null && counts.value.all === 0)
const allQuiet = computed(() => counts.value !== null && counts.value.total > 0 && counts.value.quiet === counts.value.total)
const quietLine = computed(() => {
  const n = counts.value?.total ?? 0
  // The latest end among the finished events on hand (the newest three; allQuiet means none is unfinished).
  const ends = live.latest.map((e) => e.ended_at).filter((x): x is string => x !== null)
  const since = ends.reduce<string | null>((a, b) => (a === null || Date.parse(b) > Date.parse(a) ? b : a), null)
  return since ? tp('allquiet1', 'allquiet', n, { t: dateTime(since) }) : tp('allquietever1', 'allquietever', n)
})
const located = computed(() => live.manholes.filter((m) => m.lat !== null && m.lon !== null).length)

/** The timeline range that still holds this event, so the row it opens is there to take focus back. */
function rangeFor(e: FallEvent): Range {
  const age = Date.now() - Date.parse(e.ended_at ?? new Date().toISOString())
  return age <= 24 * 3_600_000 ? '24h' : age <= 7 * 24 * 3_600_000 ? '7d' : '30d'
}

function openEvent(e: FallEvent): void {
  void router.push({ path: '/manholes', query: { range: rangeFor(e), device: e.device_id } })
}
function openDevice(id: string): void {
  void router.push({ path: '/manholes', query: { device: id } })
}

const bundles = computed(() => live.summary?.bundles ?? null)
const pois = computed(() => live.summary?.pois ?? null)
</script>

<template>
  <section class="overview">
    <div class="heading">
      <h1>{{ t('overview') }}</h1>
      <p class="small muted">{{ t('signednote') }}</p>
    </div>
    <Banner />

    <div v-if="!live.loaded" class="skeletons" :aria-label="t('loadingState')" aria-busy="true">
      <div class="skeleton strip"></div>
      <div class="grid">
        <div class="skeleton block"></div>
        <div class="skeleton block"></div>
      </div>
    </div>

    <template v-else-if="counts">
      <StatusStrip :counts="counts" :as-of="live.asOf" />
      <p v-if="empty" class="notice">{{ t('emptymanholes') }}</p>
      <p v-else-if="allQuiet" class="notice" data-testid="all-quiet">{{ quietLine }}</p>

      <div class="grid">
        <section class="panel">
          <div class="panel-head">
            <h2>{{ t('latest') }}</h2>
            <span v-if="live.asOf" class="small muted">{{ t('asof') }} {{ clock(live.asOf) }}</span>
          </div>
          <p v-if="!live.latest.length" class="empty muted">{{ t('noeventsever') }}</p>
          <EventRow
            v-for="e in live.latest"
            :key="eventKey(e)"
            :event="e"
            :device-status="byId(e.device_id)?.status"
            :show-location="byId(e.device_id)?.location_verified === false"
            @click="openEvent(e)"
          />
          <div class="panel-foot"><RouterLink to="/manholes">{{ t('viewevents') }}</RouterLink></div>
        </section>

        <section class="panel mappanel">
          <div class="panel-head">
            <h2>{{ t('map') }}</h2>
            <span class="small muted">{{ located }} / {{ tp('manholecount1', 'manholecount', counts.all) }}</span>
          </div>
          <ManholeMap :manholes="live.manholes" :pulse="live.pulse" compact @select="openDevice" />
          <MapLegend />
        </section>
        <RouterLink class="viewmap" to="/manholes">{{ t('viewmap') }}</RouterLink>
      </div>

      <section v-if="bundles" class="summaryline">
        <div>
          <h2>{{ t('copper') }}</h2>
          <p class="figures">
            <span>{{ tp('trackercount1', 'trackercount', bundles.trackers) }}</span>
            <span>{{ tf('trackeronline', { n: bundles.online }) }}</span>
            <span>{{ t('lastposition') }} {{ bundles.last_position_at ? dateTime(bundles.last_position_at) : '—' }}</span>
          </p>
        </div>
        <RouterLink to="/bundles">{{ t('viewbundles') }}</RouterLink>
      </section>
      <section v-if="pois" class="summaryline">
        <div>
          <h2>{{ t('removal') }}</h2>
          <p class="figures">
            <span>{{ pois.count }} {{ t(pois.count === 1 ? 'workorder1' : 'workorders') }}</span>
            <span>{{ pois.with_segments }} {{ t('detailcount') }}</span>
            <span>{{ tf('plannedtotal', { t: num(pois.planned_tonnes) }) }}</span>
          </p>
          <p v-if="pois.without_weight > 0" class="small muted">{{ tf('pendingweight', { n: pois.without_weight, m: pois.count }) }}</p>
        </div>
        <RouterLink to="/plan">{{ t('openplan') }}</RouterLink>
      </section>
    </template>
  </section>
</template>

<style scoped>
.heading {
  display: grid;
  gap: var(--space-xs);
  margin-bottom: var(--space-lg);
}
.notice {
  max-width: none;
  margin-top: var(--space-lg);
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
  gap: var(--space-lg);
  margin-top: var(--space-xl);
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
  font-size: var(--type-label-size);
}
.empty {
  padding: var(--space-section) var(--space-lg);
}
.viewmap {
  display: none;
}
.summaryline {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: start;
  gap: var(--space-lg);
  padding: var(--space-xl) 0;
  border-bottom: 1px solid var(--color-border);
}
.summaryline h2 {
  margin-bottom: var(--space-sm);
  font-size: var(--type-body-size);
}
.figures {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs) var(--space-xl);
}
.skeleton {
  border-radius: var(--radius-sm);
  background: var(--color-surface-raised);
}
.skeleton.strip {
  height: 104px;
}
.skeleton.block {
  height: 420px;
}
@media (max-width: 800px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 600px) {
  .mappanel {
    display: none; /* Design-Brief SCREEN-1 phone: the small map folds into a "View map" link */
  }
  .viewmap {
    display: flex;
    align-items: center;
    min-height: var(--size-touch);
  }
}
</style>
