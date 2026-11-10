<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import type { EChartsOption } from 'echarts'
import VChart from 'vue-echarts'
import ProbeMap from '../components/ProbeMap.vue'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

// Synthetic series only (no device data): 48 hourly points around 3.6 V.
const labels = Array.from({ length: 48 }, (_, i) => `${String(i % 24).padStart(2, '0')}:00`)
const values = labels.map((_, i) => Math.round((3.6 + 0.05 * Math.sin(i / 4)) * 1000) / 1000)

// ECharts' default HTML tooltip writes style="" attributes through innerHTML, which `style-src 'self'` refuses.
// richText renders the tooltip on the canvas instead. ?tooltip=html switches back so the probe can show the refusal.
const route = useRoute()
const tooltipMode = computed<'html' | 'richText'>(() => (route.query.tooltip === 'html' ? 'html' : 'richText'))

const option = computed<EChartsOption>(() => ({
  animation: false,
  grid: { left: 48, right: 16, top: 16, bottom: 32 },
  tooltip: { trigger: 'axis', renderMode: tooltipMode.value },
  xAxis: { type: 'category', data: labels },
  yAxis: { type: 'value', min: 3.5, max: 3.7 },
  series: [{ type: 'line', name: 'Synthetic voltage', data: values, showSymbol: false }],
}))
</script>

<template>
  <main class="probe">
    <h1>Lutetia — CSP probe</h1>
    <p>Synthetic data. This placeholder proves that charts and maps render under the strict CSP of /app/.</p>
    <p class="mono">tooltip renderMode: {{ tooltipMode }} · path: {{ route.fullPath }}</p>
    <VChart class="probe-chart" data-testid="probe-chart" :option="option" autoresize />
    <ProbeMap />
  </main>
</template>

<style scoped>
.probe {
  max-width: 960px;
  margin: 0 auto;
  padding: 16px;
}
.probe-chart {
  height: 320px;
  width: 100%;
  margin-bottom: 16px;
}
</style>
