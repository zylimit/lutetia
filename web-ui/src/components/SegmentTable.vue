<script setup lang="ts">
// Cable segments of one work order, inside an expanded DataTable row. A missing weight shows "weight pending", never 0.
import { num } from '../format'
import { t } from '../i18n'
import type { PoiSegment } from '../plan'

defineProps<{ segments: PoiSegment[] }>()
</script>

<template>
  <table class="segments small" role="table" data-testid="segment-table">
    <thead role="rowgroup">
      <tr role="row">
        <th role="columnheader" scope="col" class="num">{{ t('seq') }}</th>
        <th role="columnheader" scope="col">{{ t('cablecategory') }}</th>
        <th role="columnheader" scope="col">{{ t('cable') }}</th>
        <th role="columnheader" scope="col">{{ t('network') }}</th>
        <th role="columnheader" scope="col" class="num">{{ t('length') }}</th>
        <th role="columnheader" scope="col" class="num">{{ t('weight') }}</th>
      </tr>
    </thead>
    <tbody role="rowgroup">
      <tr role="row" v-for="s in segments" :key="s.seq">
        <td role="cell" class="num c-seq">{{ s.seq }}</td>
        <td role="cell" class="c-cat" :data-label="t('cablecategory')">{{ s.cable_category ?? '—' }}</td>
        <td role="cell" class="c-cable" :data-label="t('cable')">{{ s.cable_type ?? '—' }}</td>
        <td role="cell" class="c-net" :data-label="t('network')">{{ s.infra ?? '—' }}</td>
        <td role="cell" class="num c-len" :data-label="t('length')">{{ s.length_km === null ? '—' : num(s.length_km, 2) }}</td>
        <td role="cell" class="num c-wt" :data-label="t('weight')">
          <span v-if="s.weight_t === null" class="muted">{{ t('pending') }}</span>
          <template v-else>{{ num(s.weight_t, 2) }}</template>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.segments {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: var(--space-xs) var(--space-sm);
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}
th {
  color: var(--color-on-surface-muted);
  font-weight: var(--type-label-weight);
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.muted {
  color: var(--color-on-surface-muted);
}
/* Phone: each segment is a small card (sequence + cable, then the other fields with their labels) so nothing needs dragging. */
@media (max-width: 600px) {
  .segments,
  .segments tbody,
  .segments tr,
  .segments td {
    display: block;
  }
  .segments thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .segments tr {
    display: grid;
    grid-template-columns: 2em minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--space-xs) var(--space-md);
    padding: var(--space-sm) 0;
    border-bottom: 1px solid var(--color-border);
  }
  .segments td {
    padding: 0;
    border-bottom: 0;
    text-align: left;
    overflow-wrap: break-word;
  }
  .c-seq,
  .c-len,
  .c-wt {
    white-space: nowrap;
  }
  .segments td[data-label]::before {
    content: attr(data-label) ': ';
    color: var(--color-on-surface-muted);
  }
  .c-seq {
    grid-column: 1;
    grid-row: 1 / span 3;
  }
  .c-cable {
    grid-column: 2 / -1;
    grid-row: 1;
  }
  .c-cat {
    grid-column: 2;
    grid-row: 2;
  }
  .c-net {
    grid-column: 3;
    grid-row: 2;
  }
  .c-len {
    grid-column: 2;
    grid-row: 3;
  }
  .c-wt {
    grid-column: 3;
    grid-row: 3;
  }
}
</style>
