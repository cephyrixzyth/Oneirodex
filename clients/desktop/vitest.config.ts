import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'

// Mirrors the `__APP_VERSION__` define in vite.config.ts so the heartbeat's
// client_version is the real package version under test too, not a fallback.
const version = JSON.parse(
  readFileSync(fileURLToPath(new URL('./package.json', import.meta.url)), 'utf-8'),
).version as string

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  test: {
    environment: 'node',
    // Node 26 exposes a global localStorage that the companion tests do not
    // expect outside a webview. Turn it off.
    execArgv: ['--no-experimental-webstorage'],
  },
})
