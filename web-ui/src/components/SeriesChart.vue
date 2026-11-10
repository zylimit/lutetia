<script setup lang="ts">
// One line chart of the manhole drawer (voltage or signal). Tooltip renderMode richText: the default HTML tooltip writes
// style="" through innerHTML, which the strict CSP refuses (Task 9.1). Colours are read from the theme tokens at draw time.
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import type { EChartsOption } from 'echarts'
import VChart from 'vue-echarts'
import { axisStamp, dateTime, num } from '../format'
import { i18n, t } from '../i18n'
import type { SeriesPoint } from '../resources'
import { themeState } from '../theme'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

const props = defineProps<{ title: string; unit: string; points: SeriesPoint[]; digits: number }>()

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const option = computed<EChartsOption>(() => {
  void themeState.theme // redraw with the new token values when the theme changes
  void i18n.lang
  const muted = token('--color-on-surface-muted')
  const line = token('--color-on-surface')
  const border = token('--color-border')
  return {
    animation: false,
    grid: { left: 56, right: 16, top: 16, bottom: 32 },
    textStyle: { fontFamily: token('--font-sans') },
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
      backgroundColor: token('--color-surface'),
      borderColor: border,
      textStyle: { color: line },
      formatter: (params: unknown) => {
        const p = (Array.isArray(params) ? params[0] : params) as { value?: [number, number | null] }
        const [at, v] = p.value ?? [0, null]
        return `${dateTime(new Date(at).toISOString())}\n${v === null ? '—' : `${num(v, props.digits)} ${props.unit}`}`
      },
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: border } },
      axisLabel: { color: muted, hideOverlap: true, formatter: (v: number) => axisStamp(v) },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: muted, formatter: (v: number) => num(v, props.digits) },
      splitLine: { lineStyle: { color: border } },
    },
    series: [
      {
        type: 'line',
        name: props.title,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: line, width: 1.5 },
        itemStyle: { color: line },
        data: props.points.map((p) => [Date.parse(p.at), p.value]),
      },
    ],
  }
})
</script>

<template>
  <section class="linechart">
    <h3 class="small">{{ title }}</h3>
    <p v-if="!points.length" class="empty small muted">{{ t('chartempty') }}</p>
    <VChart v-else class="chart" :option="option" autoresize :aria-label="title" role="img" />
  </section>
</template>

<style scoped>
.linechart {
  display: grid;
  gap: var(--space-sm);
  margin-top: var(--space-lg);
}
.linechart h3 {
  font-size: var(--type-label-size);
}
.chart {
  height: 180px;
  width: 100%;
}
.empty {
  padding: var(--space-lg) 0;
}
</style>
