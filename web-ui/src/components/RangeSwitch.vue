<script setup lang="ts">
// CMP-5: segmented 24 h / 7 d / 30 d; the current one is shown by brightness and an underline, not a hue.
import { t } from '../i18n'
import { RANGES } from '../range'
import type { Range } from '../range'

defineProps<{ modelValue: Range }>()
const emit = defineEmits<{ 'update:modelValue': [Range] }>()

function label(r: Range): string {
  return r === '24h' ? `24 ${t('hour')}` : `${r === '7d' ? 7 : 30} ${t('days')}`
}
</script>

<template>
  <div class="segmented" role="group" :aria-label="t('range')">
    <button v-for="r in RANGES" :key="r" type="button" :aria-pressed="modelValue === r" :data-range="r" @click="emit('update:modelValue', r)">
      {{ label(r) }}
    </button>
  </div>
</template>

<style scoped>
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
  background: var(--color-surface-raised);
  color: var(--color-on-surface);
  box-shadow: inset 0 -2px var(--color-on-surface);
}
</style>
