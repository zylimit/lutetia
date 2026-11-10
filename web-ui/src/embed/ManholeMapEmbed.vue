<script setup lang="ts">
// SCREEN-E2: the manhole map (compact, as on Overview) with its legend. Selecting a marker only highlights it: v1 has no
// map message for the host, and the widget never navigates. Markers are focusable and named (IMEI + state), CMP-3.
import { computed, ref } from 'vue'
import ManholeMap from '../components/ManholeMap.vue'
import MapLegend from '../components/MapLegend.vue'
import { clock } from '../format'
import { t } from '../i18n'
import { live } from '../live'

const selected = ref<string | null>(null)
const located = computed(() => live.manholes.filter((m) => m.lat !== null && m.lon !== null).length)
</script>

<template>
  <section class="widget" :aria-label="t('map')">
    <div v-if="!live.loaded && !live.error" class="skeleton" aria-hidden="true"></div>
    <template v-else>
      <ManholeMap :manholes="live.manholes" :selected="selected" compact @select="(id: string) => (selected = id)" />
      <p v-if="live.loaded && located === 0" class="muted note">{{ t('nolocation') }}</p>
      <MapLegend />
    </template>
    <p v-if="live.asOf" class="small muted note">{{ t('asof') }} {{ clock(live.asOf) }}</p>
  </section>
</template>

<style scoped>
.skeleton {
  height: 360px; /* the compact map height (ManholeMap .compact) */
  background: var(--color-surface-raised);
}
.note {
  margin: 0;
  padding: var(--space-sm) var(--space-lg);
}
</style>
