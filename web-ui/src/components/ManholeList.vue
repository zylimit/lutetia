<script setup lang="ts">
// CMP-7: the list equivalent of the map (Design-Brief SCREEN-2 accessibility: nothing is reachable by map alone). Every
// manhole of the current filter, also those without a position; IMEI, state (icon + text), last report; a row opens the drawer.
import { computed } from 'vue'
import { dateTime } from '../format'
import { t } from '../i18n'
import type { Manhole } from '../resources'
import { markerKind } from './marker-svg'
import StatusIcon from './StatusIcon.vue'

const props = defineProps<{ manholes: Manhole[]; selected?: string | null }>()
const emit = defineEmits<{ select: [id: string, el: HTMLElement] }>()

const RANK = ['suspicious', 'moving', 'moved', 'offline', 'quiet', 'inactive']

/** Most worrying first, then the most recent report. */
const rows = computed(() =>
  props.manholes
    .map((m) => ({ m, kind: markerKind(m) }))
    .sort((a, b) => RANK.indexOf(a.kind) - RANK.indexOf(b.kind) || Date.parse(b.m.last_seen ?? '') - Date.parse(a.m.last_seen ?? '') || 0)
    .map(({ m, kind }) => ({
      id: m.device_id,
      who: m.name || m.device_id,
      kind,
      state: t(kind === 'suspicious' ? 'suspicious' : (kind as 'quiet')),
      seen: m.last_seen ? dateTime(m.last_seen, true) : t('never'),
    })),
)
</script>

<template>
  <ul class="list" :aria-label="t('manholelist')" data-testid="manhole-list">
    <li v-for="r in rows" :key="r.id">
      <button
        type="button"
        class="row"
        :class="[r.kind, { selected: selected === r.id }]"
        :data-device="r.id"
        :aria-label="`${r.who}, ${r.state}, ${t('lastreport')} ${r.seen}`"
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
  max-height: 280px;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: auto;
}
.row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: var(--space-md);
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
.who {
  overflow-wrap: anywhere;
}
.row.moved,
.row.moved .state {
  color: var(--color-warning);
}
.row.moving,
.row.suspicious {
  color: var(--color-error);
}
.row.offline,
.row.inactive {
  color: var(--color-on-surface-muted);
}
.who {
  color: var(--color-on-surface);
}
.muted {
  color: var(--color-on-surface-muted);
}
@media (max-width: 600px) {
  .row {
    grid-template-columns: 24px minmax(0, 1fr) auto;
  }
  .row time {
    grid-column: 2 / -1;
  }
}
</style>
