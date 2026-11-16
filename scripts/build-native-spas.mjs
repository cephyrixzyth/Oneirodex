import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { dirname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promoteGeneration } from './native-spa-generation.mjs'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const staticRoot = resolve(repoRoot, 'oneirodex', 'static')
const distRoot = resolve(staticRoot, 'dist')
const buildId = `${process.pid}-${Date.now()}`
const stageRoot = resolve(staticRoot, `.native-spas-stage-${buildId}`)
const backupRoot = resolve(staticRoot, `.native-spas-backup-${buildId}`)
const [major] = process.versions.node.split('.').map(Number)
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
const targets = new Map([
  ['member-app', 'index.html'],
  ['member-auth', 'auth.html'],
  ['admin-app', 'index.html'],
  ['admin-pilot', 'index.html'],
  ['ops-glance', 'index.html'],
])

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

function listFiles(directory, prefix = '') {
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const name = prefix ? `${prefix}/${entry.name}` : entry.name
      const path = join(directory, entry.name)
      if (entry.isSymbolicLink()) throw new Error(`Symlinks are not allowed in SPA output: ${name}`)
      if (entry.isDirectory()) return listFiles(path, name)
      if (!entry.isFile()) throw new Error(`Unsupported SPA output entry: ${name}`)
      return [name.split(sep).join('/')]
    })
    .sort()
}

function sourceCommit() {
  const supplied = process.env.ONEIRODEX_BUILD_SHA
  if (typeof supplied === 'string' && /^[0-9a-f]{40}$/i.test(supplied))
    return supplied.toLowerCase()
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repoRoot, encoding: 'utf8' }).trim()
  } catch {
    return null
  }
}

function buildManifest() {
  const lock = readFileSync(join(repoRoot, 'package-lock.json'))
  const builtTargets = {}
  for (const [target, entrypoint] of targets) {
    const targetRoot = join(stageRoot, target)
    const files = listFiles(targetRoot).map((path) => ({
      path,
      sha256: sha256(readFileSync(join(targetRoot, path))),
      size_bytes: statSync(join(targetRoot, path)).size,
    }))
    if (!files.some((file) => file.path === entrypoint)) {
      throw new Error(`SPA build omitted required entrypoint: ${target}/${entrypoint}`)
    }
    builtTargets[target] = { entrypoint, files }
  }
  const manifest = {
    schema_version: 1,
    source_commit: sourceCommit(),
    package_lock_sha256: sha256(lock),
    targets: builtTargets,
  }
  writeFileSync(
    join(stageRoot, 'server-ui-manifest.json'),
    `${JSON.stringify(manifest, null, 2)}\n`,
  )
}

function validateManifest() {
  const manifest = JSON.parse(readFileSync(join(stageRoot, 'server-ui-manifest.json'), 'utf8'))
  if (
    manifest.schema_version !== 1 ||
    manifest.package_lock_sha256 !== sha256(readFileSync(join(repoRoot, 'package-lock.json')))
  ) {
    throw new Error('Native SPA manifest schema or package-lock digest validation failed')
  }
  if (manifest.source_commit !== null && !/^[0-9a-f]{40}$/.test(manifest.source_commit)) {
    throw new Error('Native SPA manifest source commit is invalid')
  }
  if (Object.keys(manifest.targets).sort().join('|') !== [...targets.keys()].sort().join('|')) {
    throw new Error('Native SPA manifest does not contain exactly the five supported targets')
  }
  for (const [target, entrypoint] of targets) {
    const targetRoot = join(stageRoot, target)
    const record = manifest.targets[target]
    if (record.entrypoint !== entrypoint)
      throw new Error(`Native SPA entrypoint mismatch: ${target}`)
    const actualFiles = listFiles(targetRoot)
    const recordedFiles = record.files.map((file) => file.path).sort()
    if (actualFiles.join('|') !== recordedFiles.join('|'))
      throw new Error(`Native SPA inventory mismatch: ${target}`)
    for (const file of record.files) {
      const bytes = readFileSync(join(targetRoot, file.path))
      if (bytes.length !== file.size_bytes || sha256(bytes) !== file.sha256) {
        throw new Error(`Native SPA content validation failed: ${target}/${file.path}`)
      }
    }
  }
}

rmSync(stageRoot, { recursive: true, force: true })
mkdirSync(staticRoot, { recursive: true })
mkdirSync(stageRoot, { recursive: true })

try {
  for (const [script, workspace] of commands) {
    console.log(`\n==> Building ${workspace}:${script}`)
    execFileSync(npm, ['run', script, `--workspace=${workspace}`], {
      cwd: repoRoot,
      env: { ...process.env, ONEIRODEX_NATIVE_DIST_ROOT: stageRoot },
      shell: process.platform === 'win32',
      stdio: 'inherit',
    })
  }
  buildManifest()
  // Verify all manifest paths and bytes before moving the last working bundle.
  validateManifest()
  promoteGeneration({ current: distRoot, staged: stageRoot, backup: backupRoot })
  console.log(`\nAll ${targets.size} native installer SPA targets validated and promoted.`)
} catch (error) {
  console.error(`Native SPA build stopped before promotion: ${error.message}`)
  process.exitCode = 1
} finally {
  rmSync(stageRoot, { recursive: true, force: true })
  if (
    statSync(backupRoot, { throwIfNoEntry: false }) &&
    !statSync(distRoot, { throwIfNoEntry: false })
  ) {
    renameSync(backupRoot, distRoot)
  }
}
