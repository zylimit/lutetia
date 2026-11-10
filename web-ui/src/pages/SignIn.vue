<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import LangSwitch from '../components/LangSwitch.vue'
import { t } from '../i18n'

// Plain HTML form POST to /login (the existing, only write path of the session). The server answers with a redirect:
// success -> next (checked there), failure -> back here with ?error=1 (SCREEN-5: one message, never says which field was wrong).
const route = useRoute()

function firstQuery(value: unknown): string {
  return typeof value === 'string' ? value : Array.isArray(value) && typeof value[0] === 'string' ? value[0] : ''
}

// Convenience only: the server validates `next` again and falls back to the ops page when it is not a safe /app/ path.
const next = computed(() => {
  const raw = firstQuery(route.query.next)
  return raw.startsWith('/app/') ? raw : '/app/'
})
const errorKind = computed(() => firstQuery(route.query.error))
const errorText = computed(() => (errorKind.value === 'locked' ? t('locked') : errorKind.value ? t('wrong') : ''))

const online = ref(navigator.onLine)
function sync(): void {
  online.value = navigator.onLine
}
onMounted(() => {
  window.addEventListener('online', sync)
  window.addEventListener('offline', sync)
})
onBeforeUnmount(() => {
  window.removeEventListener('online', sync)
  window.removeEventListener('offline', sync)
})
</script>

<template>
  <main class="signinwrap">
    <section class="signin">
      <div class="brand">Ariane <span>· Copper Watch</span></div>
      <form method="post" action="/login" novalidate>
        <h1>{{ t('signin') }}</h1>
        <p class="small muted">{{ t('signednote') }}</p>
        <div v-if="!online" class="notice small" role="status">{{ t('offlinesignin') }}</div>
        <input type="hidden" name="next" :value="next" />
        <label class="field" for="username">
          {{ t('username') }}
          <input
            id="username" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false"
            required autofocus aria-describedby="login-error"
          />
        </label>
        <label class="field" for="password">
          {{ t('password') }}
          <input id="password" name="password" type="password" autocomplete="current-password" required aria-describedby="login-error" />
        </label>
        <label class="check"><input name="remember" type="checkbox" value="1" />{{ t('keep') }}</label>
        <p v-if="errorText" id="login-error" class="formerror" role="alert">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
            <path d="m8 8 8 8m0-8-8 8" stroke="currentColor" stroke-width="2" />
          </svg>
          {{ errorText }}
        </p>
        <button class="primary" type="submit">{{ t('signin') }}</button>
      </form>
      <div class="langrow"><LangSwitch /></div>
    </section>
  </main>
</template>

<style scoped>
.signinwrap {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: var(--space-xl);
}
.signin {
  width: min(100%, 384px);
}
.brand {
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-section);
  font-weight: var(--type-headline-weight);
}
.brand span {
  margin-left: var(--space-sm);
  font-weight: var(--type-body-weight);
  color: var(--color-on-surface-muted);
}
form {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  padding: var(--space-xl);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); /* the one place the 8 px ceiling is used (DESIGN.md Shapes) */
  background: var(--color-surface);
}
.field {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  min-width: 0;
}
.check {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  min-height: var(--size-input-height);
}
.formerror {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  color: var(--color-error);
  font-size: var(--type-label-size);
}
.formerror svg {
  flex: none;
  width: 18px;
  height: 18px;
}
.notice {
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-raised);
}
.primary {
  width: 100%;
  min-height: var(--size-input-height);
}
.langrow {
  display: flex;
  justify-content: center;
  margin-top: var(--space-xl);
}
@media (max-width: 600px) {
  .signinwrap {
    padding: var(--space-lg);
  }
  form {
    padding: var(--space-lg);
  }
}
</style>
