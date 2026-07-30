import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The shipped version comes from tauri.conf.json, which `scripts/release.sh`
// bumps. Reading it here means the number shown in the UI is the same one the
// installer and the updater manifest use -- a separately maintained constant
// would drift and quietly mislabel a build.
const appVersion = JSON.parse(
  readFileSync(new URL('../src-tauri/tauri.conf.json', import.meta.url), 'utf8'),
).version

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
