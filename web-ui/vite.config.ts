import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// vite-plugin-pwa is installed but deliberately NOT enabled in Phase 9 (DEV-PLAN Task 9.1).
export default defineConfig({
  base: '/app/',
  plugins: [vue()],
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    // Never inline assets as data: URIs: the /app/ CSP has font-src 'self' (no data:), so inlined fonts would be refused.
    assetsInlineLimit: 0,
  },
})
