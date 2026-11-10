<script setup lang="ts">
// CMP-9: work orders as a real <table>. A row expands to its cable segments, fetched from /api/v1/pois/{poi_no}/segments when
// opened (aria-expanded on the toggle). No weight shows "weight pending", never 0. Under a cable type / network filter the
// rows carry the tonnes of the matching segments only (Spec v1.17) and the column says so. "Open in Ariane" only with a URL. On phones the secondary columns hide and each
// row reads as a compact card (work order + expand, tonnes, subcontractor), no sideways dragging.
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
    <table class="orders" role="table" data-testid="plan-table">
      <thead role="rowgroup">
        <tr role="row">
          <th role="columnheader" scope="col">POI</th>
          <th role="columnheader" scope="col" class="wide">{{ t('uci') }}</th>
          <th role="columnheader" scope="col">{{ t('sub') }}</th>
          <th role="columnheader" scope="col" class="wide">{{ t('commune') }}</th>
          <th role="columnheader" scope="col" class="wide">{{ t('category') }}</th>
          <th role="columnheader" scope="col" class="num wide">{{ t('segments') }}</th>
          <th role="columnheader" scope="col" class="num wide">{{ t('length') }}</th>
          <th role="columnheader" scope="col" class="num">{{ t('planned') }}<span v-if="matchingOnly" class="hint"><br />{{ t('matchingonly') }}</span></th>
          <th role="columnheader" scope="col" class="wide">{{ t('received') }}</th>
          <th role="columnheader" scope="col" class="wide">{{ t('opdate') }}</th>
          <th role="columnheader" scope="col" class="wide">{{ t('occ') }}</th>
        </tr>
      </thead>
      <tbody role="rowgroup">
        <template v-for="p in rows" :key="p.poi_no">
          <tr role="row" class="order" :class="{ expanded: open.has(p.poi_no) }">
            <td role="cell" class="c-poi">
              <button type="button" class="expand mono" :aria-expanded="open.has(p.poi_no)" :aria-label="`${open.has(p.poi_no) ? t('collapse') : t('expand')} ${p.poi_no}`" @click="toggle(p)">
                <span aria-hidden="true">{{ open.has(p.poi_no) ? '−' : '+' }}</span> {{ p.poi_no }}
              </button>
            </td>
            <td role="cell" class="wide">{{ p.uci ?? '—' }}</td>
            <td role="cell" class="c-sub">{{ p.subcontractor ?? '—' }}</td>
            <td role="cell" class="wide">{{ p.site_ville ?? '—' }} <span v-if="p.commune_code" class="mono muted">{{ p.commune_code }}</span></td>
            <td role="cell" class="wide">{{ p.category ?? '—' }}</td>
            <td role="cell" class="num wide">{{ p.segment_count || '—' }}</td>
            <td role="cell" class="num wide">{{ p.total_length_km === null ? '—' : num(p.total_length_km, 2) }}</td>
            <td role="cell" class="num c-plan">
              <span class="cap small muted">{{ t('planned') }}<template v-if="matchingOnly"> · {{ t('matchingonly') }}</template></span>
              <span v-if="p.planned_tonnes === null" class="muted" data-testid="weight-pending">{{ t('pending') }}</span>
              <template v-else>{{ num(p.planned_tonnes, 2) }}</template>
            </td>
            <td role="cell" class="wide">{{ p.received_date ?? '—' }}</td>
            <td role="cell" class="wide">{{ p.planned_op_date ?? '—' }}</td>
            <td role="cell" class="wide">
              <div class="occ">
                <span>{{ p.status_raw ?? '—' }}</span>
                <a v-if="ariane(p)" :href="ariane(p) ?? undefined" target="_blank" rel="noopener noreferrer">{{ t('ariane') }}</a>
              </div>
            </td>
          </tr>
          <tr role="row" v-if="open.has(p.poi_no)" class="detail">
            <td role="cell" colspan="11">
              <p v-if="open.get(p.poi_no)?.state === 'loading'" class="small muted" aria-busy="true">{{ t('loadingState') }}</p>
              <p v-else-if="open.get(p.poi_no)?.state === 'failed'" class="small err" role="alert">{{ t('segmentsfailed') }}</p>
              <template v-else>
                <p v-if="!p.segment_count" class="small muted">{{ t('nodetail') }}</p>
                <SegmentTable v-else :segments="(open.get(p.poi_no) as { segments: PoiSegment[] }).segments" />
                <dl class="facts small">
                  <div><dt>{{ t('uci') }}</dt><dd>{{ p.uci ?? '—' }}</dd></div>
                  <div class="wrap"><dt>{{ t('commune') }}</dt><dd>{{ p.site_ville ?? '—' }} <span v-if="p.commune_code" class="mono muted">{{ p.commune_code }}</span></dd></div>
                  <div class="wrap"><dt>{{ t('category') }}</dt><dd>{{ p.category ?? '—' }}</dd></div>
                  <div><dt>{{ t('segments') }}</dt><dd>{{ p.segment_count || '—' }}</dd></div>
                  <div><dt>{{ t('length') }}</dt><dd>{{ p.total_length_km === null ? '—' : num(p.total_length_km, 2) }}</dd></div>
                  <div><dt>{{ t('received') }}</dt><dd>{{ p.received_date ?? '—' }}</dd></div>
                  <div><dt>{{ t('opdate') }}</dt><dd>{{ p.planned_op_date ?? '—' }}</dd></div>
                  <div class="wrap full">
                    <dt>{{ t('occ') }}</dt>
                    <dd>{{ p.status_raw ?? '—' }} <a v-if="ariane(p)" :href="ariane(p) ?? undefined" target="_blank" rel="noopener noreferrer">{{ t('ariane') }}</a></dd>
                  </div>
                </dl>
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
.cap {
  display: none;
}
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
}
@media (min-width: 601px) and (max-width: 800px) {
  .narrow {
    display: block;
  }
}
.facts {
  display: none;
}
/* Phone: one compact card per work order instead of a table that needs dragging. The header row stays in the DOM for
   screen readers; the grid puts the expand button (work order) and the tonnes on the first line, the subcontractor under. */
@media (max-width: 600px) {
  .tablewrap {
    max-height: none;
  }
  .orders,
  .orders tbody,
  .orders tr,
  .orders td {
    display: block;
  }
  .orders thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .orders tr.order {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-xs) var(--space-md);
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--color-border);
  }
  .orders tr.order.expanded {
    border-bottom-color: transparent;
  }
  .orders td {
    padding: 0;
    border-bottom: 0;
  }
  .orders td.wide {
    display: none; /* the id selector above would otherwise win over .wide */
  }
  /* The secondary columns (.wide) stay hidden: the card is the compact line of Design-Brief SCREEN-4. They are read in the
     expanded area (.facts) as label / value pairs in two columns. */
  .c-poi,
  .c-sub {
    overflow-wrap: anywhere;
  }
  .c-poi {
    grid-column: 1;
    grid-row: 1;
  }
  .orders td.c-plan {
    grid-column: 2;
    grid-row: 1;
    display: grid;
    justify-items: end;
    text-align: right;
  }
  .c-sub {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .cap {
    display: block;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-sm) var(--space-md);
    margin: 0 0 var(--space-md);
  }
  .facts dt {
    color: var(--color-on-surface-muted);
  }
  .facts dd {
    margin: 0;
    white-space: nowrap; /* dates, counts and codes never break */
  }
  .facts .wrap dd {
    white-space: normal;
  }
  .facts .full {
    grid-column: 1 / -1;
  }
  .expand {
    min-width: var(--size-touch);
    min-height: var(--size-touch);
  }
  .orders tr.detail {
    border-bottom: 1px solid var(--color-border);
  }
  .detail td {
    padding: var(--space-sm) var(--space-md);
  }
}
</style>
