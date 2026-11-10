<script setup lang="ts">
// CMP-11: the signed-out widget. One sentence and a link that opens sign-in in a new tab; no input of any kind here (THR-2,
// OUT-12: a framed page never takes a password). After signing in, the widget retries when its tab is visible again (data.ts).
import { SIGNIN_PATH } from '../api'
import { t } from '../i18n'
</script>

<template>
  <div class="signin-prompt" role="status" data-embed-signin>
    <p>{{ t('embedsignin') }}</p>
    <a class="open" :href="SIGNIN_PATH" target="_blank" rel="noopener" :aria-label="`${t('embedopen')} (${t('embedopenhint')})`">
      {{ t('embedopen') }}
    </a>
  </div>
</template>

<style scoped>
.signin-prompt {
  display: grid;
  justify-items: start;
  gap: var(--space-lg);
  padding: var(--space-xl);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.signin-prompt p {
  margin: 0;
}
.open {
  display: inline-flex;
  align-items: center;
  min-height: var(--size-touch);
  padding: var(--space-sm) var(--space-lg);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: var(--type-label-size);
  font-weight: var(--type-label-weight);
  text-decoration: none;
}
.open:hover {
  background: var(--color-primary-hover);
}
</style>
