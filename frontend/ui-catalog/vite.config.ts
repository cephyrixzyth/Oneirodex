import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => ({
  plugins: [react()],
  server: { host: '127.0.0.1' },
  // Keep built assets under the project hub's same-origin mount.
  base: command === 'build' ? '/ui-catalog/' : '/',
  build: { outDir: 'dist', emptyOutDir: true },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/testSetup.ts'],
  },
}))
