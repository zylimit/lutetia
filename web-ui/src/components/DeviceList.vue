<script setup lang="ts">
// CMP-7 on SCREEN-3: the list equivalent of the map. Every tracker, also those without a position. Per row: IMEI (name,
// device id only when the name is missing), state as icon + text, last position time in Europe/Paris with its zone.
import { computed } from 'vue'
import { dateTime } from '../format'
import { t } from '../i18n'
import type { Bundle } from '../resources'
import StatusIcon from './StatusIcon.vue'

const props = defineProps<{ bundles: Bundle[]; selected: string | null }>()
const emit = defineEmits<{ select: [id: string, el: HTMLElement] }>()

/** Online first, then the most recent position; trackers that never reported last. */
const rows = computed(() =>
  [...props.bundles]
    .sort((a, b) => Number(b.online) - Number(a.online) || Date.parse(b.at ?? '') - Date.parse(a.at ?? '') || 0)
    .map((b) => {
      const kind = b.online ? 'quiet' : 'offline'
      return { id: b.device_id, who: b.name || b.device_id, kind, state: t(b.online ? 'online' : 'offline'), seen: b.at ? dateTime(b.at, true) : t('never') }
    }),
)
</script>

<template>
  <ul class="list" :aria-label="t('bundlelist')" data-testid="device-list">
    <li v-for="r in rows" :key="r.id">
      <button
        type="button"
        class="row"
        :class="[r.kind, { selected: selected === r.id }]"
        :data-device="r.id"
        :aria-pressed="selected === r.id"
        :aria-label="`${r.who}, ${r.state}, ${t('lastposition')} ${r.seen}`"
        @click="emit('select', r.id, $event.currentTarget as HTMLElement)"
      >
        <StatusIcon :kind="r.kind" />
        <span class="mono who">{{ r.who }}</span>
        <span class="small state">{{ r.state }}</span>
        <time class="small mono muted">{{ r.seen }}</time>
      </button>
    </li>
  </ul>
</template>

<style scoped>
.list {
  max-height: 520px;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: auto;
}
.row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-xs) var(--space-md);
  width: 100%;
  min-height: var(--size-touch);
  padding: var(--space-sm) var(--space-lg);
  border: 0;
  border-bottom: 1px solid var(--color-border);
  border-radius: 0;
  background: var(--color-surface);
  text-align: left;
}
.row:hover,
.row.selected {
  background: var(--color-surface-raised);
}
.row.selected {
  box-shadow: inset 4px 0 0 var(--color-on-surface); /* selection is not colour alone: a thick edge as in CMP-4 */
}
.who {
  overflow-wrap: anywhere;
  color: var(--color-on-surface);
}
.row.offline,
.row.offline .state {
  color: var(--color-on-surface-muted);
}
.row time {
  grid-column: 2 / -1;
}
.muted {
  color: var(--color-on-surface-muted);
}
</style>
