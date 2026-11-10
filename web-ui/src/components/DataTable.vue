<script setup lang="ts">
// CMP-9: work orders as a real <table>. A row expands to its cable segments, fetched from /api/v1/pois/{poi_no}/segments when
// opened (aria-expanded on the toggle). No weight shows "weight pending", never 0. Under a cable type / network filter the
// rows carry the tonnes of the matching segments only (Spec v1.17) and the column says so. "Open in Ariane" only with a URL. On phones the secondary columns hide and each
// row reads as a compact line (work order, subcontractor, tonnes, expand).
import { reactive } from 'vue'
import { ApiError } from '../api'
import { num } from '../format'
import { t } from '../i18n'
import { ARIANE_PLAN_URL, getSegments } from '../plan'
import type { Poi, PoiSegment } from '../plan'
import SegmentTable from './SegmentTable.vue'

defineProps<{ rows: Poi[]; matchingOnly: boolean }>()

type Open = { state: 'loading' | 'failed' } | { state: 'ready'; segments: PoiSegment[] }
const open = reactive(new Map<string, Open>())

async function toggle(p: Poi): Promise<void> {
  if (open.has(p.poi_no)) {
    open.delete(p.poi_no)
    return
  }
  open.set(p.poi_no, { state: 'loading' })
  try {
    const segments = await getSegments(p.poi_no)
    if (open.has(p.poi_no)) open.set(p.poi_no, { state: 'ready', segments })
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return
    console.error(`segments of ${p.poi_no} failed`, e)
    if (open.has(p.poi_no)) open.set(p.poi_no, { state: 'failed' })
  }
}

function ariane(p: Poi): string | null {
  return ARIANE_PLAN_URL ? `${ARIANE_PLAN_URL}${encodeURIComponent(p.poi_no)}` : null
}
</script>

<template>
  <div class="tablewrap">
    <table class="orders" data-testid="plan-table">
      <thead>
        <tr>
          <th scope="col">POI</th>
          <th scope="col" class="wide">{{ t('uci') }}</th>
          <th scope="col">{{ t('sub') }}</th>
          <th scope="col" class="wide">{{ t('commune') }}</th>
          <th scope="col" class="wide">{{ t('category') }}</th>
          <th scope="col" class="num wide">{{ t('segments') }}</th>
          <th scope="col" class="num wide">{{ t('length') }}</th>
          <th scope="col" class="num">{{ t('planned') }}<span v-if="matchingOnly" class="hint"><br />{{ t('matchingonly') }}</span></th>
          <th scope="col" class="wide">{{ t('received') }}</th>
          <th scope="col" class="wide">{{ t('opdate') }}</th>
          <th scope="col" class="wide">{{ t('occ') }}</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="p in rows" :key="p.poi_no">
          <tr class="order" :class="{ expanded: open.has(p.poi_no) }">
            <td>
              <button type="button" class="expand mono" :aria-expanded="open.has(p.poi_no)" :aria-label="`${open.has(p.poi_no) ? t('collapse') : t('expand')} ${p.poi_no}`" @click="toggle(p)">
                <span aria-hidden="true">{{ open.has(p.poi_no) ? '−' : '+' }}</span> {{ p.poi_no }}
              </button>
            </td>
            <td class="wide">{{ p.uci ?? '—' }}</td>
            <td>{{ p.subcontractor ?? '—' }}</td>
            <td class="wide">{{ p.site_ville ?? '—' }} <span v-if="p.commune_code" class="mono muted">{{ p.commune_code }}</span></td>
            <td class="wide">{{ p.category ?? '—' }}</td>
            <td class="num wide">{{ p.segment_count || '—' }}</td>
            <td class="num wide">{{ p.total_length_km === null ? '—' : num(p.total_length_km, 2) }}</td>
            <td class="num">
              <span v-if="p.planned_tonnes === null" class="muted" data-testid="weight-pending">{{ t('pending') }}</span>
              <template v-else>{{ num(p.planned_tonnes, 2) }}</template>
            </td>
            <td class="wide">{{ p.received_date ?? '—' }}</td>
            <td class="wide">{{ p.planned_op_date ?? '—' }}</td>
            <td class="wide">
              <div class="occ">
                <span>{{ p.status_raw ?? '—' }}</span>
                <a v-if="ariane(p)" :href="ariane(p) ?? undefined" target="_blank" rel="noopener noreferrer">{{ t('ariane') }}</a>
              </div>
            </td>
          </tr>
          <tr v-if="open.has(p.poi_no)" class="detail">
            <td colspan="11">
              <p v-if="open.get(p.poi_no)?.state === 'loading'" class="small muted" aria-busy="true">{{ t('loadingState') }}</p>
              <p v-else-if="open.get(p.poi_no)?.state === 'failed'" class="small err" role="alert">{{ t('segmentsfailed') }}</p>
              <template v-else>
                <p v-if="!p.segment_count" class="small muted">{{ t('nodetail') }}</p>
                <SegmentTable v-else :segments="(open.get(p.poi_no) as { segments: PoiSegment[] }).segments" />
                <p class="small muted narrow">{{ t('occ') }}: {{ p.status_raw ?? '—' }}</p>
              </template>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.tablewrap {
  max-height: 70vh;
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.orders {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}
thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--color-surface-raised);
  font-size: var(--type-label-size);
  font-weight: var(--type-label-weight);
  white-space: nowrap;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.expand {
  min-height: auto;
  padding: var(--space-xs) var(--space-sm);
  white-space: nowrap;
}
.order.expanded td {
  border-bottom-color: transparent;
}
.detail td {
  background: var(--color-surface-raised);
}
.occ {
  display: grid;
  gap: var(--space-xs);
  min-width: 140px;
}
.occ a {
  color: var(--color-primary);
}
.hint {
  font-weight: var(--type-body-weight);
  color: var(--color-on-surface-muted);
}
.muted {
  color: var(--color-on-surface-muted);
}
.err {
  color: var(--color-error);
}
.narrow {
  display: none;
}
@media (max-width: 800px) {
  .wide {
    display: none;
  }
  .narrow {
    display: block;
  }
}
</style>
