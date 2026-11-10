<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { t } from '../i18n'
import type { Key } from '../i18n'
import { session } from '../session'
import { nextTheme, setTheme, themeState } from '../theme'
import { clock } from '../format'
import { live } from '../live'
import LangSwitch from './LangSwitch.vue'

// Project name is the only brand (DESIGN.md Overview): no logo, not translated.
const PROJECT = 'Ariane'
const SUBTITLE = '· Copper Watch'

interface Tab {
  key: Key
  to: string
  icon: string // 24x24 stroke path, same glyphs as the design prototype
}
const TABS: readonly Tab[] = [
  { key: 'overview', to: '/', icon: 'M3 3h7v7H3Zm11 0h7v7h-7ZM3 14h7v7H3Zm11 0h7v7h-7Z' },
  { key: 'manholes', to: '/manholes', icon: 'm3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2Zm6-2v16m6-14v16' },
  { key: 'bundles', to: '/bundles', icon: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM8 4v16m8-16v16' },
  { key: 'plan', to: '/plan', icon: 'M6 3h12v18H6Zm3 5h6m-6 4h6m-6 4h4' },
]

const route = useRoute()
function isCurrent(tab: Tab): boolean {
  return tab.to === '/' ? route.path === '/' : route.path === tab.to || route.path.startsWith(tab.to + '/')
}

function reload(): void {
  window.location.reload()
}

const themeLabel = computed(() => t(themeState.theme === 'projector' ? 'projection' : themeState.theme))
</script>

<template>
  <header class="topbar">
    <div class="brand">{{ PROJECT }} <span>{{ SUBTITLE }}</span></div>
    <nav class="tabs" :aria-label="t('mainnav')">
      <RouterLink v-for="tab in TABS" :key="tab.key" :to="tab.to" class="tab" :aria-current="isCurrent(tab) ? 'page' : undefined">
        {{ t(tab.key) }}
      </RouterLink>
    </nav>
    <div class="toptools">
      <span class="asof" data-testid="asof">{{ t('asof') }} {{ live.asOf ? clock(live.asOf) : '—' }}</span>
      <button type="button" class="themebutton" :aria-label="`${t('theme')}: ${themeLabel}`" @click="setTheme(nextTheme(themeState.theme))">
        {{ themeLabel }}
      </button>
      <LangSwitch />
      <details class="account">
        <summary :aria-label="t('account')">{{ session.account ?? '—' }} <span aria-hidden="true">⌄</span></summary>
        <div class="account-menu">
          <!-- POST /logout (same-origin only); next sends the browser back to this app's sign-in page -->
          <form method="post" action="/logout">
            <input type="hidden" name="next" value="/app/signin" />
            <button type="submit">{{ t('signout') }}</button>
          </form>
        </div>
      </details>
    </div>
  </header>
  <div v-if="session.checkFailed" class="notice small" role="alert">
    {{ t('sessionerror') }}
    <button type="button" @click="reload">{{ t('reload') }}</button>
  </div>
  <main class="main"><slot /></main>
  <nav class="bottomnav" :aria-label="t('mainnav')">
    <RouterLink v-for="tab in TABS" :key="tab.key" :to="tab.to" class="tab" :aria-current="isCurrent(tab) ? 'page' : undefined">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="tab.icon" fill="none" stroke="currentColor" stroke-width="1.5" /></svg>
      <span>{{ t(tab.key) }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.topbar {
  min-height: 64px;
  display: flex;
  align-items: stretch;
  gap: var(--space-xl);
  padding: 0 var(--space-xl);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.brand {
  display: flex;
  align-items: center;
  white-space: nowrap;
  font-size: var(--type-body-size);
  font-weight: var(--type-headline-weight);
}
.brand span {
  margin-left: var(--space-sm);
  font-weight: var(--type-body-weight);
  color: var(--color-on-surface-muted);
}
.tabs {
  display: flex;
  align-items: stretch;
  gap: var(--space-xs);
}
.tab {
  position: relative;
  display: flex;
  align-items: center;
  padding: var(--space-lg);
  color: var(--color-on-surface-muted);
  font-size: var(--type-label-size);
  font-weight: var(--type-label-weight);
  text-decoration: none;
}
.tab:hover {
  background: var(--color-surface-raised);
}
.tab[aria-current='page'] {
  color: var(--color-on-surface);
  box-shadow: inset 0 -3px var(--color-on-surface); /* selection = heavier edge, not a hue (DESIGN.md Colors) */
}
.toptools {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-md);
}
.asof {
  color: var(--color-on-surface-muted);
  font-size: var(--type-label-size);
  white-space: nowrap;
}
.account {
  position: relative;
}
.account summary {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  min-height: var(--size-button-height);
  padding: var(--space-sm);
  font-size: var(--type-label-size);
  cursor: pointer;
}
.account-menu {
  position: absolute;
  right: 0;
  top: 100%;
  z-index: 8;
  min-width: 160px;
  padding: var(--space-sm);
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
}
.account-menu button {
  width: 100%;
  text-align: left;
}
.notice {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md) var(--space-xl);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-error);
}
.main {
  max-width: var(--size-max-width);
  margin: auto;
  padding: var(--space-section) var(--space-xl) 96px;
}
.bottomnav {
  display: none;
}
@media (max-width: 1100px) {
  .topbar {
    flex-wrap: wrap;
    gap: var(--space-md);
    padding: 0 var(--space-lg);
  }
  .brand {
    min-height: 64px;
  }
  .tabs {
    order: 3;
    width: 100%;
    border-top: 1px solid var(--color-border);
  }
  .tab {
    flex: 1;
    justify-content: center;
  }
}
@media (max-width: 600px) {
  .topbar {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: var(--space-sm);
    padding: var(--space-md) var(--space-lg);
  }
  .brand {
    min-height: 0;
    font-size: var(--type-label-size);
  }
  .tabs,
  .themebutton {
    display: none;
  }
  .toptools {
    grid-column: 1 / -1;
    margin-left: 0;
    justify-content: space-between;
  }
  .account summary {
    min-height: var(--size-touch);
  }
  .main {
    padding: var(--space-xl) var(--space-lg) 160px;
  }
  .bottomnav {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 15;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    border-top: 1px solid var(--color-border);
    background: var(--color-surface);
    padding-bottom: env(safe-area-inset-bottom);
  }
  .bottomnav .tab {
    flex-direction: column;
    justify-content: center;
    gap: var(--space-xs);
    min-height: 64px;
    padding: var(--space-md) var(--space-xs);
  }
  .bottomnav .tab[aria-current='page'] {
    box-shadow: inset 0 3px var(--color-on-surface);
  }
  .bottomnav svg {
    width: 20px;
    height: 20px;
  }
}
</style>
