/**
 * Companion ROM patch apply (Flips IPS/BPS) — Phase 3.
 * Stages under app_data/patches/ (ACL-safe); unit tests mock Flips invoke.
 */

import { invoke } from '@tauri-apps/api/core'

import { isTauriRuntime } from './config-store.js'
import { joinUrl } from './paths.js'

const PATCH_EXTS = new Set(['.ips', '.bps', '.ups'])

export function safePatchFilename(filename: string): string {
  const trimmed = (filename || '').trim().replace(/\\/g, '/')
  const base = trimmed.split('/').pop() || ''
  const cleaned = base.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^\.+/, '')
  if (!cleaned) {
    return 'patch.bps'
  }
  return cleaned
}

export function resolvePatchStageDir(patchesDir: string, gameUuid: string): string {
  const root = patchesDir.replace(/[\\/]+$/, '')
  const safeUuid = gameUuid.replace(/[^a-zA-Z0-9_-]/g, '_')
  return `${root}/${safeUuid}`
}

export function buildFlipsApplyArgs(opts: {
  flipsPath: string
  patchPath: string
  romPath: string
  outputPath: string
}): string[] {
  // Flips CLI: flips --apply patch rom output
  return [opts.flipsPath, '--apply', opts.patchPath, opts.romPath, opts.outputPath]
}

export function isPatchFilename(name: string): boolean {
  const lower = name.toLowerCase()
  const dot = lower.lastIndexOf('.')
  if (dot < 0) {
    return false
  }
  return PATCH_EXTS.has(lower.slice(dot))
}

export function patchedOutputName(romBasename: string, patchBasename: string): string {
  const romRoot = romBasename.replace(/\.[^.]+$/, '') || 'rom'
  const lower = patchBasename.toLowerCase()
  const fmt = lower.endsWith('.ips') ? 'ips' : lower.endsWith('.ups') ? 'ups' : 'bps'
  const extMatch = romBasename.match(/(\.[^.]+)$/)
  const ext = extMatch ? extMatch[1] : '.rom'
  return `${romRoot}.patched-${fmt}${ext}`
}

async function getPatchesDir(): Promise<string> {
  if (!isTauriRuntime()) {
    return '/tmp/oneirodex/patches'
  }
  return invoke<string>('get_app_subdir', { subdir: 'patches' })
}

/**
 * Download a patch extra into companion app_data/patches/{gameUuid}/.
 */
export async function stagePatchFile(opts: {
  gameUuid: string
  patchUuid: string
  filename?: string
  apiBase?: string
  fetchImpl?: typeof fetch
  authHeader?: string
}): Promise<{ ok: true; path: string } | { ok: false; error: string }> {
  if (!isTauriRuntime()) {
    return { ok: false, error: 'Companion runtime required to stage patches' }
  }
  const base = (opts.apiBase || '').replace(/\/$/, '')
  const url = `${base}/download_other/extra/${encodeURIComponent(opts.gameUuid)}/${encodeURIComponent(opts.patchUuid)}`
  const fetchFn = opts.fetchImpl || fetch
  try {
    const headers: Record<string, string> = {}
    if (opts.authHeader) {
      headers.Authorization = opts.authHeader
    }
    const response = await fetchFn(url, { credentials: 'include', headers })
    if (!response.ok) {
      return { ok: false, error: `patch download ${response.status}` }
    }
    const buffer = await response.arrayBuffer()
    const patchesDir = await getPatchesDir()
    const stageDir = resolvePatchStageDir(patchesDir, opts.gameUuid)
    const name = safePatchFilename(opts.filename || `${opts.patchUuid}.bps`)
    const path = `${stageDir}/${name}`
    await invoke('write_file_bytes', {
      path,
      bytes: Array.from(new Uint8Array(buffer)),
    })
    return { ok: true, path }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

/**
 * Invoke Flips against staged paths under app_data/patches.
 */
export async function kickoffApplyPatch(opts: {
  gameUuid: string
  patchPath: string
  romPath: string
  outputPath?: string
}): Promise<{ ok: true; outputPath: string } | { ok: false; error: string }> {
  if (!isTauriRuntime()) {
    return {
      ok: false,
      error: 'Companion runtime required to apply patches (or apply manually with Flips)',
    }
  }
  try {
    const result = await invoke<{ output_path: string }>('run_flips_apply', {
      patchPath: opts.patchPath,
      romPath: opts.romPath,
      outputPath: opts.outputPath || null,
      gameUuid: opts.gameUuid,
    })
    return { ok: true, outputPath: result.output_path }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

/** Resolve auth-aware absolute download URL (tests / callers). */
export function patchDownloadUrl(baseUrl: string, gameUuid: string, patchUuid: string): string {
  return joinUrl(baseUrl, `/download_other/extra/${gameUuid}/${patchUuid}`)
}
