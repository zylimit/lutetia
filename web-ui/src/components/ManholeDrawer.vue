<script setup lang="ts">
// CMP-6: manhole detail in a native <dialog> (showModal: focus is trapped, Esc closes). The parent owns the selection
// (it is in the URL) and puts focus back on the element that opened the drawer once it has closed.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ApiError } from '../api'
import { clock, dateTime, num } from '../format'
import { t, tf } from '../i18n'
import { byId, imei, live } from '../live'
import { eventKey, getEventsSince, getSeries } from '../resources'
import type { FallEvent, ManholeSeries } from '../resources'
import { markerKind } from './marker-svg'
import EventRow from './EventRow.vue'
import SeriesChart from './SeriesChart.vue'
import StatusIcon from './StatusIcon.vue'

const props = defineProps<{ deviceId: string | null }>()
const emit = defineEmits<{ closed: [] }>()

const dialog = ref<HTMLDialogElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)
const days = ref<7 | 30>(7)
const series = ref<ManholeSeries | null>(null)
const events = ref<FallEvent[]>([])
const failed = ref(false)
const loading = ref(false)
let request = 0 // answers to an older request (another device, other days) are dropped

const manhole = computed(() => (props.deviceId ? byId(props.deviceId) : undefined))
const kind = computed(() => (manhole.value ? markerKind(manhole.value) : 'quiet'))
/** The truncation hint: how many readings the longer series holds and since when (the cut keeps the newest). */
const truncation = computed(() => {
  const s = series.value
  if (!s?.truncated) return ''
  const longest = s.volt.length >= s.rsrp.length ? s.volt : s.rsrp
  return longest.length ? tf('charttruncated', { n: longest.length, t: dateTime(longest[0].at) }) : ''
})
const stateLabel = computed(() => t(kind.value === 'suspicious' ? 'suspicious' : (kind.value as 'quiet')))

async function load(): Promise<void> {
  const id = props.deviceId
  if (!id) return
  const mine = ++request
  loading.value = true
  failed.value = false
  try {
    const [s, ev] = await Promise.all([getSeries(id, days.value), getEventsSince(24 * 30, id)])
    if (mine !== request) return
    series.value = s
    events.value = ev
  } catch (e) {
    if (mine !== request) return
    if (!(e instanceof ApiError && e.status === 401)) {
      failed.value = true
      console.error(`manhole ${id}: detail load failed`, e)
    }
  } finally {
    if (mine === request) loading.value = false
  }
}

async function show(id: string | null): Promise<void> {
  const d = dialog.value
  if (!d) return
  if (!id) {
    if (d.open) d.close()
    return
  }
  series.value = null
  events.value = []
  if (!d.open) d.showModal()
  await nextTick()
  closeBtn.value?.focus()
  void load()
}

watch(() => props.deviceId, show, { flush: 'post' })
onMounted(() => void show(props.deviceId)) // opened straight from a URL with ?device=
watch(days, () => void load())
watch(() => live.tick, () => props.deviceId && void load()) // the 60 s refresh also renews the open drawer

defineExpose({ dialog })
</script>

<template>
  <dialog ref="dialog" class="drawer" aria-labelledby="drawer-title" data-testid="manhole-drawer" @close="emit('closed')">
    <template v-if="deviceId">
      <div class="head">
        <div class="title">
          <h2 id="drawer-title" class="mono">{{ imei(deviceId) }}</h2>
          <span class="badge" :class="kind"><StatusIcon :kind="kind" />{{ stateLabel }}</span>
        </div>
        <button ref="closeBtn" type="button" class="close" :aria-label="t('close')" @click="dialog?.close()">×</button>
      </div>
      <p v-if="!manhole?.location_verified" class="small muted" data-testid="location-unverified">{{ t('location') }}</p>
      <p v-if="live.asOf" class="small muted">{{ t('asof') }} {{ clock(live.asOf) }}</p>
      <dl class="kv">
        <div>
          <dt>{{ t('lastreport') }}</dt>
          <dd class="mono">{{ manhole?.last_seen ? dateTime(manhole.last_seen, true) : t('never') }}</dd>
        </div>
        <div>
          <dt>{{ t('status') }}</dt>
          <dd>{{ stateLabel }}</dd>
        </div>
        <div>
          <dt>{{ t('voltage') }}</dt>
          <dd>{{ manhole?.volt == null ? '—' : `${num(manhole.volt, 2)} V` }}</dd>
        </div>
        <div>
          <dt>{{ t('signal') }}</dt>
          <dd>{{ manhole?.rsrp == null ? '—' : `${num(manhole.rsrp, 0)} dBm` }}</dd>
        </div>
      </dl>
      <div class="segmented" role="group" :aria-label="t('period')">
        <button v-for="n in [7, 30] as const" :key="n" type="button" :aria-pressed="days === n" @click="days = n">{{ n }} {{ t('days') }}</button>
      </div>
      <p v-if="failed" class="small error" role="alert">{{ t('seriesfailed') }}</p>
      <div v-if="loading && !series && !failed" class="skeleton" :aria-label="t('loadingState')" aria-busy="true"></div>
      <template v-if="series">
        <p v-if="truncation" class="small muted">{{ truncation }}</p>
        <SeriesChart :title="t('voltage')" unit="V" :digits="2" :points="series.volt" />
        <SeriesChart :title="t('signal')" unit="dBm" :digits="0" :points="series.rsrp" />
      </template>
      <h3 class="events-title">{{ t('events') }}</h3>
      <p v-if="!events.length && failed" class="small error">{{ t('eventsfailed') }}</p>
      <p v-else-if="!events.length && !loading" class="small muted">{{ t('noevents30') }}</p>
      <div v-else class="events">
        <EventRow v-for="e in events" :key="eventKey(e)" :event="e" :device-status="manhole?.status" />
      </div>
    </template>
  </dialog>
</template>

<style scoped>
.drawer {
  margin: 0 0 0 auto;
  width: min(520px, 100%);
  max-width: 100%;
  height: 100dvh;
  max-height: none;
  padding: var(--space-xl);
  border: 0;
  border-left: 1px solid var(--color-border);
  border-radius: var(--radius-none);
  background: var(--color-surface-raised);
  color: var(--color-on-surface);
  overflow: auto;
}
.drawer::backdrop {
  background: var(--color-neutral);
  opacity: 0.7;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
}
.title {
  display: grid;
  gap: var(--space-xs);
  min-width: 0;
}
.title h2 {
  overflow-wrap: anywhere;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--type-label-size);
}
.badge.moved {
  color: var(--color-warning);
}
.badge.moving,
.badge.suspicious {
  color: var(--color-error);
}
.badge.offline,
.badge.inactive {
  color: var(--color-on-surface-muted);
}
.close {
  min-width: var(--size-touch);
  min-height: var(--size-touch);
  font-size: var(--type-headline-size);
}
.kv {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-lg);
  margin: var(--space-xl) 0;
}
.kv dt {
  margin-bottom: var(--space-xs);
  color: var(--color-on-surface-muted);
  font-size: var(--type-label-size);
}
.kv dd {
  margin: 0;
}
.segmented {
  display: inline-flex;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}
.segmented button {
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--color-on-surface-muted);
}
.segmented button[aria-pressed='true'] {
  background: var(--color-surface);
  color: var(--color-on-surface);
  box-shadow: inset 0 -2px var(--color-on-surface);
}
.skeleton {
  height: 360px;
  margin-top: var(--space-lg);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}
.error {
  margin-top: var(--space-lg);
  color: var(--color-error);
}
.events-title {
  margin: var(--space-xl) 0 var(--space-md);
  font-size: var(--type-body-size);
}
.events {
  border: 1px solid var(--color-border);
}
@media (max-width: 600px) {
  .drawer {
    margin: auto 0 0;
    width: 100%;
    height: 92dvh;
    border-left: 0;
    border-top: 1px solid var(--color-border);
  }
}
</style>
