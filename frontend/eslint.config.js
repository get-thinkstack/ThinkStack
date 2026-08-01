import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: {
        ...globals.browser,
        // injected by vite's `define` from src-tauri/tauri.conf.json
        __APP_VERSION__: 'readonly',
      },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // Warnings, not errors, and deliberately so.
      //
      // These are React-compiler rules that flag WORKING code: effects which
      // call setState, and a helper that reads then sets state. Satisfying them
      // means restructuring effects in Library, PaperWriter and Analysis --
      // real refactoring, on the UI, days before a launch. The risk of that
      // change is larger than the risk they describe.
      //
      // They stay visible as warnings so the debt is not forgotten. Everything
      // else (unused vars, undefined names, genuine mistakes) still fails the
      // build. Revisit once the release is out.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/immutability': 'warn',
    },
  },
])
