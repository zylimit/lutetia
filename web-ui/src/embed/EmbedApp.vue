<script setup lang="ts">
// Shell-less frame of the three widgets (SCREEN-E1 ~ E3): no navigation, no theme or language switch. Signed out -> CMP-11 only;
// otherwise Banner (offline / error / data delayed, CMP-12) above the widget. Reports its height to the host.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Banner from '../components/Banner.vue'
import type { Range } from '../range'
import { embed, startEmbedData } from './data'
import type { Widget } from './data'
import FallTimeline from './FallTimeline.vue'
import { loadEmbedConfig, reportHeight, startHostLink } from './host'
import ManholeMapEmbed from './ManholeMapEmbed.vue'
import SecuritySummary from './SecuritySummary.vue'
import SignInPrompt from './SignInPrompt.vue'

const props = defineProps<{ widget: Widget; range: Range; deviceId: string | null }>()

const root = ref<HTMLElement | null>(null)
const stops: (() => void)[] = []

onMounted(() => {
  stops.push(startEmbedData(props.widget === 'fall-timeline', { range: props.range, deviceId: props.deviceId }))
  if (root.value) {
    const el = root.value
    stops.push(startHostLink(el))
    void loadEmbedConfig() // its first success reports the height (host.ts), even when that is a later retry
  }
})
onBeforeUnmount(() => stops.forEach((stop) => stop()))
watch(() => embed.signedOut, () => root.value && reportHeight(root.value), { flush: 'post' })
</script>

<template>
  <div ref="root" class="embed" :data-widget="widget">
    <SignInPrompt v-if="embed.signedOut" />
    <template v-else>
      <Banner />
      <FallTimeline v-if="widget === 'fall-timeline'" :range="range" />
      <ManholeMapEmbed v-else-if="widget === 'manhole-map'" />
      <SecuritySummary v-else />
    </template>
  </div>
</template>

<style scoped>
.embed {
  min-width: 280px; /* Design-Brief E1 ~ E3: width follows the host container, never below 280 px */
  width: 100%;
  background: var(--color-surface);
}
</style>
