<script setup lang="ts">
// SCREEN-E1: movement events of the chosen range (?range=24h|7d|30d, default 7d; optional ?device_id=), suspicious ones on top
// (same rule as Overview). A click selects the row and tells the host (device and time only); the widget itself never navigates.
import { computed, ref } from 'vue'
import EventRow from '../components/EventRow.vue'
import { clock } from '../format'
import { t } from '../i18n'
import type { Key } from '../i18n'
import { byId, imei, live } from '../live'
import type { Range } from '../range'
import { eventKey } from '../resources'
import type { FallEvent } from '../resources'
import { embed } from './data'
import { sendToHost } from './host'
import { fallEventSelected } from './messaging'

const props = defineProps<{ range: Range }>()
const selected = ref<string | null>(null)
const NONE: Record<Range, Key> = { '24h': 'noevents24', '7d': 'noevents', '30d': 'noevents30' }
const empty = computed(() => live.loaded && embed.events.length === 0)

function pick(e: FallEvent): void {
  selected.value = eventKey(e)
  sendToHost(fallEventSelected(e, imei(e.device_id)))
}
</script>

<template>
  <section class="widget" :aria-label="t('events')">
    <h1 class="small">{{ t('events') }}</h1>
    <div v-if="!live.loaded && !live.error" class="skeleton" aria-hidden="true"><span v-for="n in 3" :key="n"></span></div>
    <p v-else-if="empty" class="muted none">{{ t(NONE[props.range]) }}</p>
    <div v-else class="rows">
      <EventRow
        v-for="e in embed.events"
        :key="eventKey(e)"
        :event="e"
        :device-status="byId(e.device_id)?.status"
        :selected="selected === eventKey(e)"
        @click="pick(e)"
      />
    </div>
    <p v-if="live.asOf" class="small muted note">{{ t('asof') }} {{ clock(live.asOf) }}</p>
  </section>
</template>

<style scoped>
h1 {
  margin: 0;
  padding: var(--space-sm) var(--space-lg);
  font-weight: var(--type-label-weight);
}
.rows {
  border-top: 1px solid var(--color-border);
}
.none {
  margin: 0;
  padding: var(--space-lg);
}
.note {
  margin: 0;
  padding: var(--space-sm) var(--space-lg);
}
.skeleton {
  display: grid;
  gap: var(--space-sm);
  padding: var(--space-lg);
}
.skeleton span {
  height: var(--size-touch);
  background: var(--color-surface-raised);
}
</style>
