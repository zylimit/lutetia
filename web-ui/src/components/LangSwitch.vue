<script setup lang="ts">
import { i18n, setLang, t } from '../i18n'
import type { Lang } from '../i18n'

const LANGS: readonly { code: Lang; label: string }[] = [
  { code: 'en', label: 'EN' },
  { code: 'fr', label: 'FR' },
]
</script>

<template>
  <div class="lang" role="group" :aria-label="t('language')">
    <button v-for="l in LANGS" :key="l.code" type="button" :aria-pressed="i18n.lang === l.code" @click="setLang(l.code)">
      {{ l.label }}
    </button>
  </div>
</template>

<style scoped>
.lang {
  display: flex;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  padding: var(--space-xs);
}
.lang button {
  min-height: 32px;
  min-width: 40px;
  padding: var(--space-xs) var(--space-sm);
  border: 0;
  border-radius: var(--radius-full);
  background: none;
  color: var(--color-on-surface-muted);
}
.lang button[aria-pressed='true'] {
  background: var(--color-surface-raised);
  color: var(--color-on-surface);
}
@media (max-width: 600px) {
  .lang button {
    min-height: 36px;
    min-width: var(--size-touch);
  }
}
</style>
