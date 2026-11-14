import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { renameSync } from 'node:fs'

const nativeDistRoot = process.env.ONEIRODEX_NATIVE_DIST_ROOT
const outputDir = nativeDistRoot
  ? path.resolve(nativeDistRoot, 'admin-pilot')
  : path.resolve(__dirname, '../../oneirodex/static/dist/admin-pilot')

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'pilot-shell-name',
      closeBundle() {
        renameSync(path.join(outputDir, 'static-pilot.html'), path.join(outputDir, 'index.html'))
      },
    },
  ],
  base: '/static/dist/admin-pilot/',
  build: {
    outDir: outputDir,
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'static-pilot.html'),
    },
  },
})
