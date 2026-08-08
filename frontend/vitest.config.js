import { defineConfig } from 'vitest/config'

// Tests live in frontend/tests/, mirroring the module they cover, to match the
// convention CONTRIBUTING.md sets for the Python suite. Vitest would default to
// co-locating *.test.js beside the source; this repo does not do that.
//
// jsdom supplies the `window` these tests use to stand in for the tauri webview.
export default defineConfig({
  esbuild: { jsx: 'automatic' },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.{test,spec}.{js,jsx}'],
  },
})
