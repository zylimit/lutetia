<script setup lang="ts">
import { t } from '../i18n'
import type { Key } from '../i18n'

defineProps<{ title: Key }>()
</script>

<template>
  <section class="coming">
    <h1>{{ t(title) }}</h1>
    <p class="muted">{{ t('comingsoon') }}. {{ t('comingsoonhint') }}</p>
  </section>
</template>

<style scoped>
.coming {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  padding: var(--space-section) 0;
}
</style>
