<script setup lang="ts">
// Cable segments of one work order, inside an expanded DataTable row. A missing weight shows "weight pending", never 0.
import { num } from '../format'
import { t } from '../i18n'
import type { PoiSegment } from '../plan'

defineProps<{ segments: PoiSegment[] }>()
</script>

<template>
  <table class="segments small" data-testid="segment-table">
    <thead>
      <tr>
        <th scope="col" class="num">{{ t('seq') }}</th>
        <th scope="col">{{ t('cablecategory') }}</th>
        <th scope="col">{{ t('cable') }}</th>
        <th scope="col">{{ t('network') }}</th>
        <th scope="col" class="num">{{ t('length') }}</th>
        <th scope="col" class="num">{{ t('weight') }}</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="s in segments" :key="s.seq">
        <td class="num">{{ s.seq }}</td>
        <td>{{ s.cable_category ?? '—' }}</td>
        <td>{{ s.cable_type ?? '—' }}</td>
        <td>{{ s.infra ?? '—' }}</td>
        <td class="num">{{ s.length_km === null ? '—' : num(s.length_km, 2) }}</td>
        <td class="num">
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
</style>
