import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const nativeDistRoot = process.env.ONEIRODEX_NATIVE_DIST_ROOT

export default defineConfig({
  plugins: [react()],
  base: '/static/dist/ops-glance/',
  build: {
    outDir: nativeDistRoot
      ? path.resolve(nativeDistRoot, 'ops-glance')
      : path.resolve(__dirname, '../../oneirodex/static/dist/ops-glance'),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'index.html'),
      output: {
        entryFileNames: 'ops-glance.js',
        assetFileNames: 'ops-glance.[ext]',
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/testSetup.ts',
  },
})
