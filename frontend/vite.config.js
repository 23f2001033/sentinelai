import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The built SPA is emitted into the backend's static tree so the whole product
// deploys as a single service.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: {
    outDir: '../backend/app/static/app',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/demo': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
