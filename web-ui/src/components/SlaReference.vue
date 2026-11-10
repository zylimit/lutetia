<script setup lang="ts">
// SLA process reference (Task 10.3): the template of the chosen work-order category, as an ordered list of steps with the
// responsible party and the SLA duration. Reference only — no timeout is computed per work order (OUT-9). Durations are the
// values parsed at import, shown in EN / FR, with the network layer when the template gives one; the Chinese text as written is
// never shown (Decisions 2026-11-10), and a step name in CJK script reads "— (see source table)" (defence only: names are ASCII).
import { computed, ref, watch } from 'vue'
import { num } from '../format'
import { t, tf, tp } from '../i18n'
import type { Key } from '../i18n'
import { hasCjk } from '../plan'
import type { SlaStep, SlaTemplate } from '../plan'

const props = defineProps<{ templates: SlaTemplate[]; state: 'loading' | 'failed' | 'ready'; preferred: string | null }>()

const ORDER = ['Transportation', 'Distribution', 'MASSIVE']
const ordered = computed(() =>
  [...props.templates].sort((a, b) => {
    const ia = ORDER.indexOf(a.template)
    const ib = ORDER.indexOf(b.template)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.template.localeCompare(b.template)
  }),
)
const chosen = ref<string | null>(null)
watch(
  () => [props.preferred, ordered.value.map((x) => x.template).join('|')],
  () => {
    const names = ordered.value.map((x) => x.template)
    chosen.value = props.preferred && names.includes(props.preferred) ? props.preferred : (names[0] ?? null)
  },
  { immediate: true },
)
const current = computed(() => ordered.value.find((x) => x.template === chosen.value) ?? null)

const TEMPLATE_LABEL: Record<string, Key> = { Transportation: 'tplTransportation', Distribution: 'tplDistribution', MASSIVE: 'tplMASSIVE' }
const OWNER_LABEL: Record<string, Key> = { customer: 'ownercustomer', huawei: 'ownerhuawei', partner: 'ownerpartner' }
const UNIT: Record<string, [Key, Key]> = {
  minute: ['uminute1', 'uminute'],
  hour: ['uhour1', 'uhour'],
  day: ['uday1', 'uday'],
  workday: ['uworkday1', 'uworkday'],
  week: ['uweek1', 'uweek'],
  month: ['umonth1', 'umonth'],
  tonne_per_day: ['utonne_per_day1', 'utonne_per_day'],
}

function label(name: string): string {
  return TEMPLATE_LABEL[name] ? t(TEMPLATE_LABEL[name]) : name
}

/** "2 working days", "1–2 days", "2 t/day"; null when there is nothing parsed to show. */
function duration(s: SlaStep): string | null {
  const keys = s.sla_unit ? UNIT[s.sla_unit] : undefined
  if (s.sla_value === null || !keys) return null
  const n = s.sla_value_min !== null ? `${num(s.sla_value_min, 2)}–${num(s.sla_value, 2)}` : num(s.sla_value, 2)
  const d = tp(keys[0], keys[1], s.sla_value_min !== null ? 2 : s.sla_value, { n })
  return s.sla_scope && SCOPE_LABEL[s.sla_scope] ? tf(SCOPE_LABEL[s.sla_scope], { d }) : s.sla_scope ? tf('scopeother', { d }) : d
}

/** "Access layer: 1 t/day"; an unknown prefix in the template reads "1 t/day (scope in source table)". */
const SCOPE_LABEL: Record<string, Key> = { access: 'scopeaccess', aggregation: 'scopeaggregation', backbone: 'scopebackbone' }
</script>

<template>
  <section class="sla" data-testid="sla-reference" aria-labelledby="sla-title">
    <div class="head">
      <h2 id="sla-title">{{ t('sla') }}</h2>
      <p class="small muted">{{ t('refonly') }}</p>
    </div>
    <div v-if="state === 'loading'" class="skeleton" aria-busy="true" :aria-label="t('loadingState')"></div>
    <p v-else-if="state === 'failed'" class="small err" role="alert">{{ t('slafailed') }}</p>
    <p v-else-if="!ordered.length" class="small muted" data-testid="sla-empty">{{ t('slanone') }}</p>
    <template v-else>
      <div class="choices" role="group" :aria-label="t('sla')">
        <button v-for="x in ordered" :key="x.template" type="button" :aria-pressed="x.template === chosen" @click="chosen = x.template">
          {{ label(x.template) }}<span v-if="x.template === preferred" class="hint"> · {{ t('slamatch') }}</span>
        </button>
      </div>
      <ol v-if="current" class="steps" data-testid="sla-steps">
        <li v-for="s in current.steps" :key="s.seq" class="step">
          <span class="seq mono">{{ s.seq }}</span>
          <span v-if="hasCjk(s.step)" class="name">— <span class="muted">({{ t('seesource') }})</span></span>
          <span v-else class="name">{{ s.step }}</span>
          <span class="owner small">{{ OWNER_LABEL[s.owner] ? t(OWNER_LABEL[s.owner]) : s.owner }}</span>
          <span class="dur small">
            <template v-if="duration(s)">{{ duration(s) }}</template>
            <template v-else-if="s.sla_text">— <span class="muted">({{ t('seesource') }})</span></template>
            <template v-else>—</template>
          </span>
        </li>
      </ol>
    </template>
  </section>
</template>

<style scoped>
.sla {
  margin-top: var(--space-section);
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.head {
  display: grid;
  gap: var(--space-xs);
  margin-bottom: var(--space-lg);
}
.head h2 {
  font-size: var(--type-headline-size);
}
.choices {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-lg);
}
.choices button[aria-pressed='true'] {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.steps {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.step {
  display: grid;
  grid-template-columns: 2.5em minmax(0, 1fr) 8em 11em;
  gap: var(--space-md);
  align-items: baseline;
  padding: var(--space-sm) 0;
  border-bottom: 1px solid var(--color-border);
}
.seq {
  text-align: right;
  color: var(--color-on-surface-muted);
}
.muted {
  color: var(--color-on-surface-muted);
}
.err {
  color: var(--color-error);
}
.skeleton {
  height: 200px;
  background: var(--color-surface-raised);
  border-radius: var(--radius-sm);
}
@media (max-width: 600px) {
  .step {
    grid-template-columns: 2em minmax(0, 1fr);
  }
  .owner,
  .dur {
    grid-column: 2;
  }
}
</style>
