<script setup lang="ts">
// SCREEN-E3: the security status strip of Overview (CMP-1), same counts and "as of", without links (a widget never navigates).
import { computed } from 'vue'
import StatusStrip from '../components/StatusStrip.vue'
import { t } from '../i18n'
import { live } from '../live'

const counts = computed(() => live.summary?.manholes ?? null)
</script>

<template>
  <section class="widget" :aria-label="t('security')">
    <div v-if="counts === null && !live.error" class="skeleton" aria-hidden="true"></div>
    <StatusStrip v-else-if="counts" :counts="counts" :as-of="live.asOf" linkless />
  </section>
</template>

<style scoped>
.skeleton {
  height: 96px; /* about one strip row */
  background: var(--color-surface-raised);
}
</style>
