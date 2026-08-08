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
    // Bind every loopback family. Vite picked [::1] only on this machine, so
    // http://127.0.0.1:3000 refused the connection while http://localhost:3000
    // worked, which looks exactly like "the UI is not running".
    host: true,
    proxy: {
      '/api': {
        // 127.0.0.1, not localhost: the backend binds IPv4 only, and localhost
        // resolves to ::1 first on current systems. The packaged app hit the
        // same trap in its loading screen.
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
