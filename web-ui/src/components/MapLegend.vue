<script setup lang="ts">
import { t } from '../i18n'
import type { Key } from '../i18n'
import StatusIcon from './StatusIcon.vue'

const ITEMS: readonly { kind: string; key: Key }[] = [
  { kind: 'quiet', key: 'quiet' },
  { kind: 'moved', key: 'moved' },
  { kind: 'moving', key: 'moving' },
  { kind: 'offline', key: 'offline' },
  { kind: 'suspicious', key: 'suspicious' },
  { kind: 'inactive', key: 'inactive' },
]
</script>

<template>
  <div class="legend small" role="list" :aria-label="t('legend')">
    <span v-for="it in ITEMS" :key="it.kind" class="item" :class="it.kind" role="listitem"><StatusIcon :kind="it.kind" />{{ t(it.key) }}</span>
    <span class="item muted" role="listitem"><span class="corner" aria-hidden="true"></span>{{ t('location') }}</span>
  </div>
</template>

<style scoped>
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs) var(--space-md);
  padding: var(--space-md) var(--space-lg);
  border-top: 1px solid var(--color-border);
}
.item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
}
.moved {
  color: var(--color-warning);
}
.moving,
.suspicious {
  color: var(--color-error);
}
.offline,
.inactive {
  color: var(--color-on-surface-muted);
}
.corner {
  width: 8px;
  height: 8px;
  border: 1px solid var(--color-on-surface-muted);
  background: var(--color-surface);
}
</style>
