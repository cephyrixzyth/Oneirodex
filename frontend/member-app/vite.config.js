import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const nativeDistRoot = process.env.ONEIRODEX_NATIVE_DIST_ROOT

export default defineConfig({
  plugins: [react()],
  base: '/static/dist/member-app/',
  build: {
    outDir: nativeDistRoot
      ? path.resolve(nativeDistRoot, 'member-app')
      : path.resolve(__dirname, '../../oneirodex/static/dist/member-app'),
    emptyOutDir: true,
    cssCodeSplit: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'index.html'),
      output: {
        entryFileNames: 'member-app.js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          // Keep a stable entry stylesheet for any static link; chunk CSS stay hashed
          // so lazy routes do not collide on member-app.css / member-app2.css.
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            const names = assetInfo.names || []
            const isEntryCss =
              names.some((n) => n === 'index.css' || n === 'style.css') ||
              assetInfo.name === 'index.css' ||
              assetInfo.name === 'style.css'
            if (isEntryCss) {
              return 'member-app.css'
            }
            return 'chunks/[name]-[hash][extname]'
          }
          return 'assets/[name]-[hash][extname]'
        },
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('react-dom') || id.includes('/react/') || id.includes('react-router')) {
              return 'react-vendor'
            }
          }
          return undefined
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/testSetup.ts',
    // userEvent interactions take ~9s on a network-mounted checkout; the 5s
    // default fails them spuriously while they pass fine given room to run.
    //
    // Two tests used to cross even this in a full run while passing in seconds
    // alone. Raising the number to 90s did not fix them, which was the useful
    // result: the cause was that those two files were the only ones importing
    // user-event *inside a test body*, so vitest's first resolve+transform of
    // that module ran against the test clock instead of during collection.
    // They import it at module scope now, and this stays at 30s — a timeout
    // generous enough to hide a real hang is not doing its job.
    testTimeout: 30000,
  },
})
