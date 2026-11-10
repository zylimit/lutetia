<script setup lang="ts">
// CMP-8: six exact-match filters of /api/v1/pois. The parent keeps the values in the URL; chosen values show as removable tags
// and "Clear filters" empties them all. A value from a shared link that is not among today's options is still offered.
import { computed } from 'vue'
import { t, tf } from '../i18n'
import type { Key } from '../i18n'
import { FILTER_KEYS } from '../plan'
import type { FilterKey, Filters } from '../plan'

const props = defineProps<{ filters: Filters; options: Record<FilterKey, string[]> }>()
const emit = defineEmits<{ change: [key: FilterKey, value: string | null]; clear: [] }>()

const LABELS: Record<FilterKey, Key> = {
  uci: 'uci',
  subcontractor: 'sub',
  commune: 'commune',
  category: 'category',
  network: 'infrastructure',
  cable_type: 'cable',
}

function choices(k: FilterKey): string[] {
  const v = props.filters[k]
  return v && !props.options[k].includes(v) ? [v, ...props.options[k]] : props.options[k]
}

const active = computed(() => FILTER_KEYS.filter((k) => !!props.filters[k]))

function onChange(k: FilterKey, ev: Event): void {
  const v = (ev.target as HTMLSelectElement).value
  emit('change', k, v || null)
}
</script>

<template>
  <section class="filterbar" :aria-label="t('filters')" data-testid="filter-bar">
    <div class="fields">
      <label v-for="k in FILTER_KEYS" :key="k" class="field small">
        <span>{{ t(LABELS[k]) }}</span>
        <select :name="k" :value="filters[k] ?? ''" @change="onChange(k, $event)">
          <option value="">{{ t('all') }}</option>
          <option v-for="v in choices(k)" :key="v" :value="v">{{ v }}</option>
        </select>
      </label>
    </div>
    <div v-if="active.length" class="tags">
      <button v-for="k in active" :key="k" type="button" class="tag" :aria-label="tf('removefilter', { f: `${t(LABELS[k])} ${filters[k]}` })" @click="emit('change', k, null)">
        <span class="muted">{{ t(LABELS[k]) }}:</span> {{ filters[k] }} <span aria-hidden="true">×</span>
      </button>
      <button type="button" class="linklike" data-testid="clear-filters" @click="emit('clear')">{{ t('clear') }}</button>
    </div>
  </section>
</template>

<style scoped>
.filterbar {
  display: grid;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
}
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--space-md);
}
.field {
  display: grid;
  gap: var(--space-xs);
  min-width: 0;
}
select {
  width: 100%;
  min-height: var(--size-button-height);
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}
.tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
}
.tag {
  border-radius: var(--radius-full);
  max-width: 100%;
  overflow-wrap: anywhere;
}
.linklike {
  border-color: transparent;
  background: transparent;
  text-decoration: underline;
}
.muted {
  color: var(--color-on-surface-muted);
}
@media (max-width: 600px) {
  select {
    min-height: var(--size-touch);
  }
}
</style>
