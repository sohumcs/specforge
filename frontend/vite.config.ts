/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, the SPA and API share one origin through this proxy, exactly like
// production (nginx serves the SPA and proxies /api). Same origin means the
// httpOnly refresh cookie (SameSite=Strict, path /api/v1/auth) just works and
// CORS never comes into play.
const API = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API, changeOrigin: false },
      '/health': API,
      '/ready': API,
      '/docs': API,
      '/openapi.json': API,
    },
  },
  build: { sourcemap: true, chunkSizeWarningLimit: 900 },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'], // e2e/*.spec.ts belong to Playwright
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    coverage: { provider: 'v8', include: ['src/**'], exclude: ['src/test/**'] },
  },
})
