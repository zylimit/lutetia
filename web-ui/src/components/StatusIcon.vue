<script setup lang="ts">
// The prototype's status glyphs (demo/index.html icon()): shape carries the state, so colour is never the only cue.
defineProps<{ kind: string }>()
</script>

<template>
  <svg class="status-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <template v-if="kind === 'moved'">
      <path d="M12 3 22 21H2Z" fill="none" stroke="currentColor" stroke-width="2" />
      <path d="M12 9v5m0 3v1" stroke="currentColor" stroke-width="2" />
    </template>
    <path v-else-if="kind === 'moving'" d="M12 3 22 21H2Z" fill="currentColor" />
    <template v-else-if="kind === 'offline' || kind === 'suspicious'">
      <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2" />
      <path d="m5 19 14-14" stroke="currentColor" stroke-width="2" />
    </template>
    <circle v-else-if="kind === 'inactive'" cx="12" cy="12" r="3" fill="currentColor" />
    <template v-else-if="kind === 'error'">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
      <path d="m8 8 8 8m0-8-8 8" stroke="currentColor" stroke-width="2" />
    </template>
    <circle v-else cx="12" cy="12" r="5" fill="currentColor" />
  </svg>
</template>

<style scoped>
.status-icon {
  display: inline-block;
  flex: none;
  width: 1.2em;
  height: 1.2em;
}
</style>
