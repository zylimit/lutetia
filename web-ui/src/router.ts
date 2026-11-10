import { createRouter, createWebHistory } from 'vue-router'
import CspProbe from './pages/CspProbe.vue'

// Task 9.1: one placeholder page. Every path under /app/ renders it, which also exercises the server-side
// history fallback (/app/manholes must come back as index.html). Real pages arrive in Task 9.2 / 9.3.
export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [{ path: '/:pathMatch(.*)*', name: 'probe', component: CspProbe }],
})
