import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { renameSync } from 'node:fs'

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'pilot-shell-name',
      closeBundle() {
        const output = path.resolve(__dirname, '../../oneirodex/static/dist/admin-pilot')
        renameSync(path.join(output, 'static-pilot.html'), path.join(output, 'index.html'))
      },
    },
  ],
  base: '/static/dist/admin-pilot/',
  build: {
    outDir: path.resolve(__dirname, '../../oneirodex/static/dist/admin-pilot'),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'static-pilot.html'),
    },
  },
})
