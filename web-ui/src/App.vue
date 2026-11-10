<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppShell from './components/AppShell.vue'

// The sign-in page is a bare centred form; every other page lives inside the shell (top bar, tabs, bottom bar on phones).
const route = useRoute()
const bare = computed(() => route.name === 'signin')
</script>

<template>
  <RouterView v-if="bare" />
  <AppShell v-else><RouterView /></AppShell>
</template>
