<script setup lang="ts">
// CMP-10: where the numbers come from and when they were imported. The POI ledger's authority is Ariane; Lutetia shows an Excel
// snapshot (Spec v1.12). `source` comes from the resource: "ariane" switches to the From-Ariane wording (Design-Brief CMP-10).
import { computed } from 'vue'
import { dateTime } from '../format'
import { tf } from '../i18n'

const props = defineProps<{ asOf: string | null; source: string }>()

const text = computed(() => {
  const at = props.asOf ? dateTime(props.asOf) : '—'
  return props.source === 'ariane' ? tf('sourceariane', { t: at }) : tf('sourcesnapshot', { t: at })
})
</script>

<template>
  <p class="source small" data-testid="source-note">{{ text }}</p>
</template>

<style scoped>
.source {
  margin: 0 0 var(--space-lg);
  padding: var(--space-md) var(--space-lg);
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
  color: var(--color-on-surface-muted);
}
</style>
