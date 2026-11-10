<script setup lang="ts">
// CMP-1: three mutually exclusive bands of the in-use manholes (moved in 24 h incl. moving, offline, online and quiet);
// they add up to summary.manholes.total. Inactive ones are counted apart, below (Decisions 2026-11-09 / 2026-11-10).
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { clock } from '../format'
import { t, tf, tp } from '../i18n'
import type { Key } from '../i18n'
import type { Summary } from '../resources'
import StatusIcon from './StatusIcon.vue'

const props = defineProps<{ counts: Summary['manholes']; asOf: string | null }>()

interface Item {
  filter: 'moved' | 'offline' | 'quiet'
  n: number
  label: Key
  aria: Key
  aria1: Key
  icon: string
  tone: '' | 'warn' | 'alarm'
  note: string
}

const items = computed<Item[]>(() => {
  const c = props.counts
  return [
    {
      filter: 'moved',
      n: c.moved_24h,
      label: 'moved24',
      aria: 'movedaria',
      aria1: 'movedaria1',
      icon: c.moving > 0 ? 'moving' : 'moved',
      tone: c.moving > 0 ? 'alarm' : c.moved_24h > 0 ? 'warn' : '',
      note: c.moving > 0 ? tf('movingcount', { n: c.moving }) : '',
    },
    {
      filter: 'offline',
      n: c.offline,
      label: 'offline',
      aria: 'offlinearia',
      aria1: 'offlinearia1',
      icon: c.offline_with_open_event > 0 ? 'suspicious' : 'offline',
      tone: c.offline_with_open_event > 0 ? 'alarm' : '',
      note: c.offline_with_open_event > 0 ? tf('offlineopen', { n: c.offline_with_open_event }) : '',
    },
    { filter: 'quiet', n: c.quiet, label: 'online', aria: 'onlinearia', aria1: 'onlinearia1', icon: 'quiet', tone: '', note: '' },
  ]
})
</script>

<template>
  <div class="statusstrip" role="group" :aria-label="t('security')">
    <RouterLink
      v-for="it in items"
      :key="it.filter"
      class="statusitem"
      :class="it.tone"
      :to="{ path: '/manholes', query: { status: it.filter } }"
      :aria-label="tp(it.aria1, it.aria, it.n) + (it.note ? `, ${it.note}` : '')"
      :data-status-filter="it.filter"
    >
      <StatusIcon :kind="it.icon" />
      <span class="stat">
        <strong>{{ it.n }}</strong>
        <span class="small">{{ t(it.label) }}</span>
        <span v-if="it.note" class="small note">{{ it.note }}</span>
      </span>
    </RouterLink>
    <div class="side small">
      <span v-if="asOf" class="muted">{{ t('asof') }} {{ clock(asOf) }}</span>
      <RouterLink v-if="counts.inactive > 0" :to="{ path: '/manholes', query: { status: 'inactive' } }" class="muted">
        {{ tp('inactivecount1', 'inactivecount', counts.inactive) }}
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.statusstrip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) auto;
  align-items: stretch;
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.statusitem {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  min-width: 0;
  padding: var(--space-xl);
  border-right: 1px solid var(--color-border);
  color: var(--color-on-surface);
  text-decoration: none;
  transition: background var(--motion-feedback) var(--motion-easing);
}
.statusitem:hover {
  background: var(--color-surface-raised);
}
.statusitem .status-icon {
  width: 24px;
  height: 24px;
}
.statusitem.warn {
  color: var(--color-warning);
}
.statusitem.alarm {
  color: var(--color-error);
}
.stat {
  display: grid;
  gap: var(--space-xs);
  min-width: 0;
}
.stat strong {
  font-size: var(--type-display-size);
  font-weight: var(--type-display-weight);
  line-height: var(--type-display-line);
}
.side {
  display: grid;
  align-content: center;
  gap: var(--space-xs);
  padding: var(--space-lg);
}
@media (max-width: 1100px) {
  .statusstrip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .side {
    grid-column: 1 / -1;
    border-top: 1px solid var(--color-border);
    padding: var(--space-sm) var(--space-lg);
  }
  .statusitem {
    padding: var(--space-lg);
    gap: var(--space-sm);
  }
}
@media (max-width: 600px) {
  .statusitem {
    flex-direction: column;
    align-items: flex-start;
  }
  .statusitem:last-of-type {
    border-right: 0;
  }
  .stat strong {
    font-size: var(--type-headline-size);
  }
  .side a {
    display: flex;
    align-items: center;
    min-height: var(--size-touch);
  }
}
</style>
