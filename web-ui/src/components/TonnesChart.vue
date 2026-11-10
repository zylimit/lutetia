<script setup lang="ts">
// One horizontal bar chart of planned tonnes (Plan page). Tooltip renderMode richText: the HTML tooltip writes style="" through
// innerHTML, which the strict CSP refuses (Task 9.1). Colours come from the theme tokens at draw time.
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import type { EChartsOption } from 'echarts'
import VChart from 'vue-echarts'
import { num } from '../format'
import { i18n, t } from '../i18n'
import type { Bar } from '../plan'
import { themeState } from '../theme'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const props = defineProps<{ title: string; bars: Bar[]; testid: string }>()

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const labels = computed(() => props.bars.map((b) => b.label ?? t('notset')))

const option = computed<EChartsOption>(() => {
  void themeState.theme // redraw with the new token values when the theme changes
  void i18n.lang
  const muted = token('--color-on-surface-muted')
  const text = token('--color-on-surface')
  const border = token('--color-border')
  return {
    animation: false,
    grid: { left: 8, right: 56, top: 8, bottom: 24, containLabel: true },
    textStyle: { fontFamily: token('--font-sans') },
    tooltip: {
      trigger: 'item',
      renderMode: 'richText',
      backgroundColor: token('--color-surface'),
      borderColor: border,
      textStyle: { color: text },
      formatter: (p: unknown) => {
        const { name, value } = p as { name: string; value: number }
        return `${name}\n${num(value, 1)} t`
      },
    },
    xAxis: { type: 'value', axisLabel: { color: muted, formatter: (v: number) => num(v, 0) }, splitLine: { lineStyle: { color: border } } },
    yAxis: { type: 'category', inverse: true, data: labels.value, axisLabel: { color: text, width: 160, overflow: 'truncate' }, axisLine: { lineStyle: { color: border } } },
    series: [
      {
        type: 'bar',
        name: props.title,
        barMaxWidth: 20,
        itemStyle: { color: token('--color-primary') },
        label: { show: true, position: 'right', color: text, formatter: (p: unknown) => num((p as { value: number }).value, 1) },
        data: props.bars.map((b) => Math.round(b.tonnes * 10) / 10),
      },
    ],
  }
})
</script>

<template>
  <section class="barchart" :data-testid="testid">
    <h3 class="small">{{ title }}</h3>
    <p v-if="!bars.length" class="empty small muted">{{ t('chartnone') }}</p>
    <VChart v-else class="chart" :class="{ tall: bars.length > 6 }" :option="option" autoresize :aria-label="title" role="img" />
  </section>
</template>

<style scoped>
.barchart {
  display: grid;
  gap: var(--space-sm);
  min-width: 0;
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.barchart h3 {
  font-size: var(--type-label-size);
}
.chart {
  width: 100%;
  height: 220px;
}
.chart.tall {
  height: 400px;
}
.empty {
  padding: var(--space-lg) 0;
}
.muted {
  color: var(--color-on-surface-muted);
}
</style>
