import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

const nativeDistRoot = process.env.ONEIRODEX_NATIVE_DIST_ROOT

export default defineConfig({
  plugins: [react()],
  base: '/static/dist/member-auth/',
  build: {
    outDir: nativeDistRoot
      ? path.resolve(nativeDistRoot, 'member-auth')
      : path.resolve(__dirname, '../../oneirodex/static/dist/member-auth'),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'auth.html'),
      output: {
        entryFileNames: 'member-auth.js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
})
