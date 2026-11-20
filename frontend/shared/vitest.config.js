import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Contract tests for `@oneirodex/ui` live next to the modules they cover
// (`src/*.test.*`). jsdom + the jest-dom matchers because the DOM helpers
// (confirmDialog, toast, csrf) and the React surface (PageStatus, useRailState)
// both need a document.
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    // Node 26 exposes its own global localStorage, which shadows jsdom's
    // Storage. Turn it off so tests see the browser-like environment.
    execArgv: ['--no-experimental-webstorage'],
    setupFiles: './src/testSetup.ts',
  },
})
