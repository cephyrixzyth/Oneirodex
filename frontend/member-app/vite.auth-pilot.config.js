import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  base: '/static/dist/member-auth/',
  build: {
    outDir: path.resolve(__dirname, '../../oneirodex/static/dist/member-auth'),
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
