import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const [major, minor] = process.versions.node.split('.').map(Number)
if (major !== 22) {
  console.error(`Native installer SPA builds require Node 22; found ${process.versions.node}.`)
  process.exit(2)
}

const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const commands = [
  ['build', 'member-app'],
  ['build:auth-pilot', 'member-app'],
  ['build', 'admin-app'],
  ['build:pilot', 'admin-app'],
  ['build', 'ops-glance'],
]

for (const [script, workspace] of commands) {
  console.log(`\n==> Building ${workspace}:${script}`)
  execFileSync(npm, ['run', script, `--workspace=${workspace}`], {
    cwd: repoRoot,
    shell: process.platform === 'win32',
    stdio: 'inherit',
  })
}

const outputs = new Map([
  ['member-app', 'index.html'],
  ['member-auth', 'auth.html'],
  ['admin-app', 'index.html'],
  ['admin-pilot', 'index.html'],
  ['ops-glance', 'index.html'],
])
const missing = [...outputs].filter(([name, entry]) =>
  !existsSync(resolve(repoRoot, 'oneirodex', 'static', 'dist', name, entry)),
).map(([name]) => name)
if (missing.length) {
  console.error(`SPA build completed without required entry points: ${missing.join(', ')}`)
  process.exit(1)
}

console.log(`\nAll ${outputs.size} native installer SPA entry points are present.`)
