<script setup lang="ts">
// CMP-4: one movement event. IMEI (mono), start to the second in Europe/Paris with its abbreviation, duration ("Ongoing"
// while unfinished), flips, and the reserved "Notified —" slot (no notification channel yet, Design-Brief DQ-1).
import { computed } from 'vue'
import { dateTime, duration } from '../format'
import { t } from '../i18n'
import { imei } from '../live'
import type { FallEvent } from '../resources'
import StatusIcon from './StatusIcon.vue'

const props = defineProps<{ event: FallEvent; deviceStatus?: string; selected?: boolean; showLocation?: boolean }>()

/** An unfinished event of a manhole that is now offline is the suspicious case (Decisions 2026-11-10): marked apart. */
const kind = computed(() => {
  if (props.event.ended_at !== null) return 'moved'
  return props.deviceStatus === 'offline' ? 'suspicious' : 'moving'
})
const label = computed(() => t(kind.value === 'suspicious' ? 'suspicious' : kind.value === 'moving' ? 'moving' : 'moved'))
const who = computed(() => imei(props.event.device_id))
const started = computed(() => dateTime(props.event.started_at, true))
</script>

<template>
  <button
    type="button"
    class="event"
    :class="{ selected }"
    :data-device="event.device_id"
    :data-kind="kind"
    :aria-label="`${t('event')} ${who}, ${label}, ${started}`"
  >
    <span class="glyph"><StatusIcon :kind="kind" /></span>
    <span class="info">
      <span class="top">
        <span class="mono">{{ who }}</span>
        <span class="small state">{{ label }}</span>
      </span>
      <time class="mono muted" :datetime="event.started_at">{{ started }}</time>
      <span class="meta">
        <span>{{ t('duration') }}<span>{{ event.duration_sec === null ? t('ongoing') : duration(event.duration_sec) }}</span></span>
        <span>{{ t('flips') }}<span>{{ event.flips }}</span></span>
        <span>{{ t('notified') }}<span>—</span></span>
      </span>
      <span v-if="showLocation" class="small muted">{{ t('location') }}</span>
    </span>
  </button>
</template>

<style scoped>
.event {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: var(--space-sm);
  width: 100%;
  min-height: 0;
  padding: var(--space-lg);
  border: 0;
  border-bottom: 1px solid var(--color-border);
  border-radius: 0;
  background: var(--color-surface);
  text-align: left;
  font-size: var(--body-size);
  font-weight: var(--type-body-weight);
  line-height: var(--type-body-line);
}
.event:hover {
  background: var(--color-surface-raised);
}
.event[data-kind='moved'] {
  box-shadow: inset 3px 0 var(--color-warning);
}
.event[data-kind='moving'],
.event[data-kind='suspicious'] {
  box-shadow: inset 3px 0 var(--color-error);
}
.event.selected {
  background: var(--color-surface-raised);
  box-shadow: inset 6px 0 var(--color-on-surface);
}
.glyph {
  display: flex;
  padding-top: 2px;
}
.event[data-kind='moved'] .glyph,
.event[data-kind='moved'] .state {
  color: var(--color-warning);
}
.event[data-kind='moving'] .glyph,
.event[data-kind='moving'] .state,
.event[data-kind='suspicious'] .glyph,
.event[data-kind='suspicious'] .state {
  color: var(--color-error);
}
.info {
  display: grid;
  gap: var(--space-xs);
  min-width: 0;
}
.top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-sm);
}
.top .mono {
  overflow-wrap: anywhere;
}
.meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-sm);
  color: var(--color-on-surface-muted);
  font-size: var(--type-label-size);
}
.meta > span > span {
  display: block;
  color: var(--color-on-surface);
}
</style>
