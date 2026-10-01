/**
 * Companion PC mod pack apply (MOD-3).
 * Fetches enabled mod metadata from Oneirodex, stages under app_data/mods/{uuid}/,
 * then applies path-safely into the local install directory.
 *
 * WebRetro cannot load arbitrary PC mods — companion-only apply path.
 */

import { formatBearerAuthorization } from '@oneirodex/api-client'
import { invoke } from '@tauri-apps/api/core'

import type { AuthStore } from './auth.js'
import { isTauriRuntime } from './config-store.js'
import { isPathUnderRoot } from './path-guard.js'
import { loadInstallsFromDisk } from './install-store.js'
import { checkModSourceUrl } from './transport-policy.js'

export interface GameModRow {
  id: string
  name: string
  version: string
  source_url: string
  enabled: boolean
  load_order: number
  /** INSP-36 — the loader this mod needs (`bepinex`, `smapi`, …); `''` when unsaid. Read, never installed. */
  loader: string
  /** INSP-38 — ids of rows this one needs staged first. */
  requires: string[]
}

export interface GameModsResponse {
  enabled: boolean
  mods: GameModRow[]
  /** Pack-level loader the librarian set; rows without their own inherit it in the hint. */
  default_loader: string
  /** INSP-37 — the profile whose set is currently enabled, by name; `''` when none. */
  active_profile_name: string
}

const ZIP_EXTS = new Set(['.zip', '.7z'])

export function safeModFilename(filename: string): string {
  const trimmed = (filename || '').trim().replace(/\\/g, '/')
  const base = trimmed.split('/').pop() || ''
  const cleaned = base.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^\.+/, '')
  if (!cleaned) {
    return 'mod.bin'
  }
  return cleaned
}

export function safeModRelativePath(relativePath: string): string | null {
  const normalized = (relativePath || '').replace(/\\/g, '/').replace(/^\/+/, '')
  if (!normalized || normalized.includes('..')) {
    return null
  }
  const parts = normalized.split('/').filter(Boolean)
  if (parts.length === 0) {
    return null
  }
  const safeParts = parts.map((part) => safeModFilename(part))
  return safeParts.join('/')
}

export function resolveModStageDir(modsDir: string, gameUuid: string, modId: string): string {
  const root = modsDir.replace(/[\\/]+$/, '')
  const safeUuid = gameUuid.replace(/[^a-zA-Z0-9_-]/g, '_')
  const safeModId = modId.replace(/[^a-zA-Z0-9_-]/g, '_')
  return `${root}/${safeUuid}/${safeModId}`
}

export function resolveModApplyPath(installRoot: string, relativePath: string): string | null {
  const safeRelative = safeModRelativePath(relativePath)
  if (!safeRelative) {
    return null
  }
  const sep = installRoot.includes('\\') ? '\\' : '/'
  const root = installRoot.replace(/[\\/]+$/, '')
  const candidate = `${root}${sep}${safeRelative.replace(/\//g, sep)}`
  if (!isPathUnderRoot(candidate, root)) {
    return null
  }
  return candidate
}

export function isModArchiveFilename(name: string): boolean {
  const lower = name.toLowerCase()
  const dot = lower.lastIndexOf('.')
  if (dot < 0) {
    return false
  }
  return ZIP_EXTS.has(lower.slice(dot))
}

export function pickModFilename(sourceUrl: string, mod: GameModRow): string {
  try {
    const url = new URL(sourceUrl)
    const last = url.pathname.split('/').pop()
    if (last) {
      return safeModFilename(decodeURIComponent(last))
    }
  } catch {
    // fall through
  }
  const ext = isModArchiveFilename(mod.name) ? '' : '.zip'
  return safeModFilename(`${mod.id}${ext || '.zip'}`)
}

/**
 * Enabled rows with a source URL, by load order — and a row always after the
 * rows it `requires` (INSP-38), so a dependency lands before its dependent
 * whatever the librarian typed for load order. Cycles fall back to load order.
 */
export function sortEnabledMods(mods: GameModRow[]): GameModRow[] {
  const base = mods
    .filter((row) => row.enabled && row.source_url.trim())
    .slice()
    .sort((a, b) => a.load_order - b.load_order || a.name.localeCompare(b.name))
  const byId = new Map(base.map((row) => [row.id, row]))
  const out: GameModRow[] = []
  const placed = new Set<string>()
  const visiting = new Set<string>()
  const visit = (row: GameModRow) => {
    if (placed.has(row.id) || visiting.has(row.id)) return
    visiting.add(row.id)
    for (const dep of row.requires || []) {
      const target = byId.get(dep)
      if (target) visit(target)
    }
    visiting.delete(row.id)
    placed.add(row.id)
    out.push(row)
  }
  base.forEach(visit)
  return out
}

/** No-loader words: a row saying one of these never conflicts with the pack default. */
const NO_LOADER = new Set(['', 'manual', 'none'])

/**
 * INSP-38 — enabled rows whose loader disagrees with the pack default. Apply
 * refuses on these unless the caller overrides; a mod built for MelonLoader
 * dropped into a BepInEx install does nothing at best.
 */
export function loaderConflicts(
  pack: Pick<GameModsResponse, 'mods' | 'default_loader'>,
): { id: string; name: string; loader: string }[] {
  const def = (pack.default_loader || '').trim().toLowerCase()
  if (NO_LOADER.has(def)) return []
  return pack.mods
    .filter((row) => row.enabled)
    .map((row) => ({ id: row.id, name: row.name, loader: (row.loader || '').trim().toLowerCase() }))
    .filter((row) => !NO_LOADER.has(row.loader) && row.loader !== def)
}

async function getModsDir(): Promise<string> {
  if (!isTauriRuntime()) {
    return '/tmp/oneirodex/mods'
  }
  return invoke<string>('get_app_subdir', { subdir: 'mods' })
}

export async function fetchGameMods(
  auth: AuthStore,
  gameUuid: string,
  options: { fetchImpl?: typeof fetch } = {},
): Promise<GameModsResponse> {
  const baseUrl = auth.getBaseUrl()
  const token = auth.getToken()
  if (!baseUrl || !token) {
    return { enabled: false, mods: [], default_loader: '', active_profile_name: '' }
  }
  const fetchImpl = options.fetchImpl ?? fetch
  const response = await fetchImpl(
    `${baseUrl.replace(/\/$/, '')}/api/games/${encodeURIComponent(gameUuid)}/mods`,
    { headers: { Authorization: formatBearerAuthorization(token) } },
  )
  if (!response.ok) {
    throw new Error(`mods fetch ${response.status}`)
  }
  const data = (await response.json().catch(() => ({}))) as {
    enabled?: boolean
    mods?: unknown
    default_loader?: unknown
    profiles?: unknown
    active_profile?: unknown
  }
  const mods = Array.isArray(data.mods)
    ? data.mods.flatMap((row) => {
        if (!row || typeof row !== 'object') {
          return []
        }
        const record = row as Record<string, unknown>
        const id = String(record.id || '').trim()
        if (!id) {
          return []
        }
        return [
          {
            id,
            name: String(record.name || id),
            version: String(record.version || ''),
            source_url: String(record.source_url || record.url || '').trim(),
            enabled: record.enabled !== false,
            load_order: Number(record.load_order) || 0,
            loader: String(record.loader || '').trim(),
            requires: Array.isArray(record.requires)
              ? (record.requires as unknown[]).map((v) => String(v)).filter(Boolean)
              : [],
          },
        ]
      })
    : []
  const activeId = String(data.active_profile || '').trim()
  const activeName = Array.isArray(data.profiles)
    ? String(
        (data.profiles as Array<Record<string, unknown>>).find(
          (p) => p && String(p.id) === activeId,
        )?.name || '',
      )
    : ''
  return {
    enabled: data.enabled !== false,
    mods,
    default_loader: String(data.default_loader || '').trim(),
    active_profile_name: activeId ? activeName : '',
  }
}

const LOADER_LABELS: Record<string, string> = {
  bepinex: 'BepInEx',
  melonloader: 'MelonLoader',
  smapi: 'SMAPI',
  lovely: 'lovely',
  forge: 'Forge',
  fabric: 'Fabric',
  quilt: 'Quilt',
  neoforge: 'NeoForge',
}

/** Human name for a loader slug; unknown slugs are shown as typed. */
export function loaderLabel(loader: string): string {
  const key = (loader || '').trim().toLowerCase()
  return LOADER_LABELS[key] || loader.trim()
}

/**
 * The loaders the enabled mods need (INSP-36): each row's own `loader`, else the
 * pack's `default_loader`. `manual` and `none` mean "no loader", and are dropped.
 */
export function requiredLoaders(pack: Pick<GameModsResponse, 'mods' | 'default_loader'>): string[] {
  const seen = new Set<string>()
  for (const mod of pack.mods) {
    if (!mod.enabled) continue
    const loader = (mod.loader || pack.default_loader || '').trim().toLowerCase()
    if (!loader || loader === 'manual' || loader === 'none') continue
    seen.add(loader)
  }
  return Array.from(seen)
}

/**
 * One line for the apply flow: which loaders must already be installed. The
 * companion applies mod files; it never installs a loader.
 */
export function loaderRequirementHint(
  pack: Pick<GameModsResponse, 'mods' | 'default_loader'>,
): string | null {
  const loaders = requiredLoaders(pack)
  if (loaders.length === 0) return null
  const names = loaders.map(loaderLabel).join(', ')
  return `Needs ${names} installed — not managed here.`
}

export async function fetchModsSummaryGameUuids(
  auth: AuthStore,
  options: { fetchImpl?: typeof fetch } = {},
): Promise<{ gameUuids: Set<string>; trackingEnabled: boolean }> {
  const baseUrl = auth.getBaseUrl()
  const token = auth.getToken()
  if (!baseUrl || !token) {
    return { gameUuids: new Set(), trackingEnabled: false }
  }
  const fetchImpl = options.fetchImpl ?? fetch
  const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/api/mods/summary`, {
    headers: { Authorization: formatBearerAuthorization(token) },
  })
  if (!response.ok) {
    return { gameUuids: new Set(), trackingEnabled: false }
  }
  const data = (await response.json().catch(() => ({}))) as {
    enabled?: boolean
    games?: unknown
  }
  if (data.enabled === false) {
    return { gameUuids: new Set(), trackingEnabled: false }
  }
  const uuids = new Set<string>()
  if (Array.isArray(data.games)) {
    for (const row of data.games) {
      if (!row || typeof row !== 'object') {
        continue
      }
      const record = row as Record<string, unknown>
      const gameUuid = String(record.game_uuid || '').trim()
      const enabledCount = Number(record.enabled_count) || 0
      if (gameUuid && enabledCount > 0) {
        uuids.add(gameUuid)
      }
    }
  }
  return { gameUuids: uuids, trackingEnabled: true }
}

/**
 * INSP-39 — integrity: a staged file must be whole. An empty body, or a body
 * shorter than the `Content-Length` the server declared, is refused before it
 * is written, so a half download never reaches an install folder. The caller
 * re-stages from `source_url` on the next apply — that is the repair.
 */
export function checkDownloadIntegrity(
  buffer: ArrayBuffer,
  declaredLength: string | null,
  modName: string,
): string | null {
  if (buffer.byteLength === 0) {
    return `mod download for ${modName} was empty`
  }
  const declared = declaredLength ? Number(declaredLength) : NaN
  if (Number.isFinite(declared) && declared > 0 && buffer.byteLength < declared) {
    return `mod download for ${modName} was short (${buffer.byteLength} of ${declared} bytes)`
  }
  return null
}

export async function stageModFromUrl(opts: {
  gameUuid: string
  mod: GameModRow
  fetchImpl?: typeof fetch
}): Promise<{ ok: true; path: string } | { ok: false; error: string }> {
  if (!isTauriRuntime()) {
    return { ok: false, error: 'Companion runtime required to stage mods' }
  }
  const url = opts.mod.source_url.trim()
  if (!url) {
    return { ok: false, error: `Mod ${opts.mod.name} has no source URL` }
  }
  // The archive is unpacked into a game folder: refuse a source that can be
  // rewritten in transit (plain http:// to a host outside the local network).
  const sourceCheck = checkModSourceUrl(url)
  if (!sourceCheck.ok) {
    return { ok: false, error: `${opts.mod.name}: ${sourceCheck.message}` }
  }
  const fetchFn = opts.fetchImpl || fetch
  try {
    const response = await fetchFn(url)
    // An https source may redirect; the hop it lands on has to pass the same check.
    // (Mocks and some runtimes leave `url` empty — nothing to check then.)
    if (response.url) {
      const finalCheck = checkModSourceUrl(response.url)
      if (!finalCheck.ok) {
        return { ok: false, error: `${opts.mod.name}: ${finalCheck.message}` }
      }
    }
    if (!response.ok) {
      return { ok: false, error: `mod download ${response.status} (${opts.mod.name})` }
    }
    const buffer = await response.arrayBuffer()
    const integrity = checkDownloadIntegrity(
      buffer,
      response.headers?.get?.('content-length') ?? null,
      opts.mod.name,
    )
    if (integrity) {
      return { ok: false, error: integrity }
    }
    const modsDir = await getModsDir()
    const stageDir = resolveModStageDir(modsDir, opts.gameUuid, opts.mod.id)
    const filename = pickModFilename(url, opts.mod)
    const path = `${stageDir}/${filename}`
    await invoke('write_file_bytes', {
      path,
      bytes: Array.from(new Uint8Array(buffer)),
    })
    return { ok: true, path }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

export async function applyStagedModToInstall(opts: {
  stagedPath: string
  installRoot: string
}): Promise<{ ok: true; applied: number } | { ok: false; error: string }> {
  if (!isTauriRuntime()) {
    return { ok: false, error: 'Companion runtime required to apply mods' }
  }
  if (!isPathUnderRoot(opts.installRoot, opts.installRoot)) {
    return { ok: false, error: 'Invalid install root' }
  }
  try {
    const result = await invoke<{ applied: number }>('apply_staged_mod', {
      sourcePath: opts.stagedPath,
      installRoot: opts.installRoot,
    })
    return { ok: true, applied: result.applied }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

export function modApplyBlockedReason(opts: {
  connectionOnline: boolean
  modsTrackingEnabled: boolean
  hasEnabledMods: boolean
  installed: boolean
}): string | null {
  if (!opts.modsTrackingEnabled) {
    return 'Mod tracking is disabled on this server.'
  }
  if (!opts.connectionOnline) {
    return 'Server offline — reconnect to fetch mod metadata and download BYO source URLs.'
  }
  if (!opts.hasEnabledMods) {
    return 'No enabled mods with source URLs for this game.'
  }
  if (!opts.installed) {
    return 'Install the game locally first, then apply mods from the companion.'
  }
  return null
}

export function modApplyUiHint(connectionOnline: boolean): string {
  if (!connectionOnline) {
    return 'Apply mods needs an online server connection (BYO URLs). WebRetro cannot apply PC mods.'
  }
  return 'Applies enabled mods into the local install folder. WebRetro cannot load PC mods.'
}

/**
 * Fetch enabled mods, stage each BYO download, apply into the game install dir.
 */
export async function kickoffApplyModPack(
  auth: AuthStore,
  gameUuid: string,
  options: { fetchImpl?: typeof fetch; allowLoaderMismatch?: boolean } = {},
): Promise<
  | {
      ok: true
      appliedMods: number
      filesApplied: number
      loaderHint: string | null
      profileName: string
    }
  | { ok: false; error: string }
> {
  if (!isTauriRuntime()) {
    return {
      ok: false,
      error: 'Companion runtime required to apply mod packs (browser cannot write install dirs)',
    }
  }

  const pack = await fetchGameMods(auth, gameUuid, options)
  if (!pack.enabled) {
    return { ok: false, error: 'Mod tracking is disabled on this server' }
  }
  const enabled = sortEnabledMods(pack.mods)
  if (enabled.length === 0) {
    return { ok: false, error: 'No enabled mods with source URLs' }
  }
  const conflicts = loaderConflicts(pack)
  if (conflicts.length > 0 && !options.allowLoaderMismatch) {
    const names = conflicts.map((c) => `${c.name} (${c.loader})`).join(', ')
    return {
      ok: false,
      error: `Loader mismatch — the pack is set to ${pack.default_loader} but ${names} need a different loader. Fix the rows or the default, or apply anyway from the row's menu.`,
    }
  }
  const loaderHint = loaderRequirementHint(pack)

  const installs = await loadInstallsFromDisk()
  const install = installs[gameUuid]
  if (!install?.extractPath) {
    return { ok: false, error: 'Game is not installed locally — install first' }
  }

  let appliedMods = 0
  let filesApplied = 0
  for (const mod of enabled) {
    const staged = await stageModFromUrl({ gameUuid, mod, fetchImpl: options.fetchImpl })
    if (!staged.ok) {
      return { ok: false, error: staged.error }
    }
    const applied = await applyStagedModToInstall({
      stagedPath: staged.path,
      installRoot: install.extractPath,
    })
    if (!applied.ok) {
      return { ok: false, error: applied.error }
    }
    appliedMods += 1
    filesApplied += applied.applied
  }

  return { ok: true, appliedMods, filesApplied, loaderHint, profileName: pack.active_profile_name }
}
