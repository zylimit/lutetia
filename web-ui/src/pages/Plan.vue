<script setup lang="ts">
// SCREEN-4: the removal plan (Excel snapshot of the POI ledger; Ariane is the source of truth). Six filters live in the URL so a
// refresh or a shared link restores them. The two charts count only the work orders with cable detail and say how many they
// cover — the same rule as /api/v1/summary pois.with_segments (Spec "only work orders with cable detail have planned tonnes").
// The table and the CSV export hold every filtered row (all API pages), so table rows = CSV data rows.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import DataTable from '../components/DataTable.vue'
import FilterBar from '../components/FilterBar.vue'
import SlaReference from '../components/SlaReference.vue'
import SourceNote from '../components/SourceNote.vue'
import TonnesChart from '../components/TonnesChart.vue'
import { ApiError } from '../api'
import { csvFileName, download, toCsv } from '../csv'
import type { Cell } from '../csv'
import { i18n, t, tf, tp } from '../i18n'
import { live, refresh, useLive } from '../live'
import { distinct, FILTER_KEYS, getPois, getSegmentsOf, getSlaTemplates, hasWeight, segmentFiltered, templateFor, tonnesByCableType,
  tonnesBySubcontractor, withMatchingTonnes } from '../plan'
import type { FilterKey, Filters, Poi, PoiSegment, SlaTemplate } from '../plan'

const route = useRoute()
const router = useRouter()
const filters = computed<Filters>(() => {
  const f: Filters = {}
  for (const k of FILTER_KEYS) {
    const v = route.query[k]
    if (typeof v === 'string' && v) f[k] = v
  }
  return f
})
const filtered = computed(() => FILTER_KEYS.some((k) => !!filters.value[k]))

const base = ref<Poi[]>([]) // every work order: filter options and the segments behind the cable-type chart
const segments = ref(new Map<string, PoiSegment[]>())
const segState = ref<'loading' | 'failed' | 'ready'>('loading')
const rows = ref<Poi[]>([])
const asOf = ref<string | null>(null)
const source = ref('excel-snapshot')
const loaded = ref(false)
const failed = ref(false)
const sla = ref<SlaTemplate[]>([])
const slaState = ref<'loading' | 'failed' | 'ready'>('loading')
const exportFailed = ref(false)
let rowsReq = 0
let baseReq = 0

async function loadBase(): Promise<void> {
  const mine = ++baseReq
  try {
    const all = await getPois({})
    if (mine !== baseReq) return
    base.value = all.items
    const segs = await getSegmentsOf(all.items.filter((p) => p.segment_count > 0).map((p) => p.poi_no))
    if (mine !== baseReq) return
    segments.value = segs
    segState.value = 'ready'
  } catch (e) {
    if (mine !== baseReq || (e instanceof ApiError && e.status === 401)) return
    if (segState.value !== 'ready') segState.value = 'failed' // a failed background reload keeps the chart on screen
    console.error('plan segments load failed', e)
  }
}

async function loadRows(): Promise<void> {
  const mine = ++rowsReq
  try {
    const r = await getPois(filters.value)
    if (mine !== rowsReq) return
    const reimported = loaded.value && r.asOf !== asOf.value
    rows.value = r.items
    asOf.value = r.asOf
    source.value = r.source
    loaded.value = true
    failed.value = false
    if (reimported) void loadBase() // a new import since the last load: options and segments too
  } catch (e) {
    if (mine !== rowsReq || (e instanceof ApiError && e.status === 401)) return
    failed.value = true // the rows on screen stay as they were
    console.error('work orders load failed', e)
  }
}

async function loadSla(): Promise<void> {
  try {
    sla.value = (await getSlaTemplates()).items
    slaState.value = 'ready'
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return
    if (slaState.value !== 'ready') slaState.value = 'failed'
    console.error('SLA templates load failed', e)
  }
}

let stop: (() => void) | null = null
onMounted(() => {
  stop = useLive() // banner state (offline, collector delay) and the shared 60 s tick
  void loadRows()
  void loadBase()
  void loadSla()
})
onBeforeUnmount(() => stop?.())
watch(filters, () => void loadRows())
watch(() => live.tick, () => void loadRows())

function setFilter(k: FilterKey, v: string | null): void {
  const query = { ...route.query }
  if (v) query[k] = v
  else delete query[k]
  void router.replace({ query })
}

function clearFilters(): void {
  const query = { ...route.query }
  for (const k of FILTER_KEYS) delete query[k]
  void router.replace({ query })
}

function reload(): void {
  void loadRows()
  void loadBase()
  void refresh()
}

const options = computed<Record<FilterKey, string[]>>(() => {
  const segs = [...segments.value.values()].flat()
  return {
    uci: distinct(base.value.map((p) => p.uci)),
    subcontractor: distinct(base.value.map((p) => p.subcontractor)),
    commune: distinct(base.value.map((p) => p.commune_code)),
    category: distinct(base.value.map((p) => p.category)),
    network: distinct(segs.map((s) => s.infra)),
    cable_type: distinct(segs.map((s) => s.cable_type)),
  }
})
/** cable_type / network filter segments: tonnes (charts, table, CSV) then count only the matching segments (Spec v1.17), which
 * needs the segments; until they are in, the page stays in its loading state rather than show whole-order tonnes. */
const segOnly = computed(() => segmentFiltered(filters.value))
const ready = computed(() => loaded.value && (!segOnly.value || segState.value === 'ready'))
const view = computed(() => withMatchingTonnes(rows.value, segments.value, filters.value))
const covered = computed(() => view.value.filter(hasWeight).length)
const bySub = computed(() => tonnesBySubcontractor(view.value))
const byCable = computed(() => tonnesByCableType(view.value, segments.value, filters.value))
const preferredSla = computed(() => templateFor(filters.value.category))

const CSV_HEADER = ['poi_no', 'uci', 'subcontractor', 'site_ville', 'commune_code', 'category', 'segment_count', 'total_length_km',
  'planned_tonnes', 'received_date', 'planned_op_date', 'occ_status']

function exportCsv(): void {
  try {
    const data: Cell[][] = view.value.map((p) => [p.poi_no, p.uci, p.subcontractor, p.site_ville, p.commune_code, p.category,
      p.segment_count, p.total_length_km, p.planned_tonnes ?? 'weight pending', p.received_date, p.planned_op_date, p.status_raw])
    download(csvFileName(), toCsv(CSV_HEADER, data, i18n.lang === 'fr' ? ';' : ',')) // FR Excel splits on semicolons (Spec v1.17)
    exportFailed.value = false
  } catch (e) {
    exportFailed.value = true
    console.error('CSV export failed', e)
  }
}
</script>

<template>
  <section class="plan">
    <div class="heading">
      <h1 tabindex="-1">{{ t('plan') }}</h1>
      <button type="button" class="primary" data-testid="export-csv" :disabled="!ready || !rows.length" @click="exportCsv">{{ t('exportcsv') }}</button>
    </div>
    <SourceNote :as-of="asOf" :source="source" />
    <Banner />
    <div v-if="failed && !live.error" class="failed" role="alert" data-testid="plan-error">
      <span>{{ t('planfailed') }}</span>
      <button type="button" @click="reload">{{ t('reload') }}</button>
    </div>
    <p v-if="exportFailed" class="failed" role="alert">{{ t('exportfailed') }}</p>

    <FilterBar :filters="filters" :options="options" @change="setFilter" @clear="clearFilters" />

    <p v-if="loaded && segOnly && segState === 'failed'" class="panel small err" role="alert">{{ t('cablechartfailed') }}</p>
    <template v-else-if="!ready">
      <div class="charts" aria-busy="true" :aria-label="t('loadingState')">
        <div class="skeleton chart"></div>
        <div class="skeleton chart"></div>
      </div>
      <div class="skeleton rows"></div>
    </template>
    <p v-else-if="!rows.length && !filtered" class="panel empty" data-testid="plan-empty">{{ t('noorders') }}</p>
    <div v-else-if="!rows.length" class="panel empty" data-testid="plan-nomatch">
      <p>{{ t('nomatch') }}</p>
      <button type="button" @click="clearFilters">{{ t('clear') }}</button>
    </div>
    <template v-else>
      <p class="small muted" data-testid="chart-coverage">{{ tf('covers', { n: covered, m: rows.length }) }}<template v-if="segOnly"> · {{ t('matchingonly') }}</template></p>
      <div class="charts">
        <TonnesChart :title="t('bysub')" :bars="bySub" testid="chart-sub" />
        <p v-if="segState === 'failed'" class="panel small err" role="alert">{{ t('cablechartfailed') }}</p>
        <div v-else-if="segState === 'loading'" class="skeleton chart" aria-busy="true" :aria-label="t('loadingState')"></div>
        <TonnesChart v-else :title="t('bycable')" :bars="byCable" testid="chart-cable" />
      </div>
      <div class="tablehead">
        <h2>{{ t('orders') }}</h2>
        <span class="small muted" data-testid="row-count">{{ tp('ordercount1', 'ordercount', rows.length) }}</span>
      </div>
      <DataTable :rows="view" :matching-only="segOnly" />
    </template>

    <SlaReference :templates="sla" :state="slaState" :preferred="preferredSla" />
  </section>
</template>

<style scoped>
.heading,
.tablehead {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}
.tablehead {
  margin-top: var(--space-section);
}
.tablehead h2 {
  font-size: var(--type-headline-size);
}
.failed {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-md);
  margin: 0 0 var(--space-lg);
  padding: var(--space-md) var(--space-lg);
  border: 1px solid var(--color-error);
  background: var(--color-surface-raised);
  color: var(--color-error);
}
.failed button {
  margin-left: auto;
  color: inherit;
}
.charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-lg);
  margin-top: var(--space-sm);
}
.panel {
  margin: 0;
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.empty {
  display: grid;
  justify-items: start;
  gap: var(--space-md);
  padding: var(--space-section) var(--space-lg);
}
.empty p {
  margin: 0;
}
.muted {
  color: var(--color-on-surface-muted);
}
.err {
  color: var(--color-error);
}
.skeleton {
  background: var(--color-surface-raised);
  border-radius: var(--radius-md);
}
.skeleton.chart {
  height: 260px;
}
.skeleton.rows {
  height: 320px;
  margin-top: var(--space-section);
}
@media (max-width: 800px) {
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>
