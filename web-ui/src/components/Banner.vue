<script setup lang="ts">
// CMP-12: one banner at a time (banner.ts pickBanner: offline first, then error > data delayed). Old data stays on screen under it.
import { computed } from 'vue'
import { offlineAsOf } from '../banner'
import { clock, clockOrDay } from '../format'
import { t, tf } from '../i18n'
import { banner, live, refresh } from '../live'
import StatusIcon from './StatusIcon.vue'

const text = computed(() => {
  switch (banner.value) {
    case 'error':
      return t('errorbanner')
    case 'stale': {
      const at = live.summary?.collector.updated_at
      return at ? tf('delaybanner', { t: clock(at) }) : t('delaybannernever')
    }
    case 'offline': {
      const at = offlineAsOf(live.pageAsOf, live.asOf)
      return at ? tf('offlinebanner', { t: clockOrDay(at) }) : t('offlinebannernone')
    }
    default:
      return ''
  }
})
</script>

<template>
  <div v-if="banner" class="banner" :class="banner" :role="banner === 'error' ? 'alert' : 'status'" :data-banner="banner">
    <StatusIcon :kind="banner === 'error' ? 'error' : banner === 'stale' ? 'moved' : 'offline'" />
    <span>{{ text }}</span>
    <button v-if="banner === 'error'" type="button" :disabled="live.loading" @click="refresh">{{ t('reload') }}</button>
  </div>
</template>

<style scoped>
.banner {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
  padding: var(--space-md) var(--space-lg);
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
}
.banner.stale {
  color: var(--color-warning);
  border-color: var(--color-warning);
}
.banner.error {
  color: var(--color-error);
  border-color: var(--color-error);
}
.banner button {
  margin-left: auto;
  color: inherit;
}
</style>
