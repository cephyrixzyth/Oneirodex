/**
 * Native RetroArch companion launch profiles (Wave 8–12).
 * Heavy systems (GC/Wii/PS2) stay native-only via RetroArch CLI.
 */

import { invoke } from '@tauri-apps/api/core'

import { isTauriRuntime } from './config-store.js'

export interface RetroArchAiTranslateHint {
  enabled?: boolean
  serviceUrl?: string
  targetLang?: string
}

/** Native PC platforms — never stage RetroArch `.cht` (Wave 19 GM lock). */
export const PC_PLATFORMS_NO_RETROARCH_CHEATS = ['PCWIN', 'PCDOS', 'MAC', 'OTHER'] as const

export interface RetroArchProfile {
  core: string
  system: string
  romPath: string
  retroarchPath?: string
  extraArgs?: string[]
  /** Optional Oneirodex game UUID — used when staging cheats before launch */
  gameUuid?: string
  /** Override staging root (must be under companion app_data/cheats when writing) */
  cheatsDir?: string
  cheatFilename?: string
  /**
   * Server launch/browse payload (`cheat_surface`).
   * Stage `.cht` only when `retroarch`. Soft-degrade when absent: hide for PC_* platforms.
   */
  cheatSurface?: string | null
  apiBase?: string
  /** Optional AI Service overlay hint (config in RetroArch UI; CLI does not set URL reliably) */
  aiTranslate?: RetroArchAiTranslateHint
  /**
   * INSP-43 — how the cabinet was driven (`joystick` | `spinner` | `lightgun`
   * | `trackball`). Selects a per-family RetroArch input remap so a spinner
   * game does not launch bound like a stick game. Unknown families and
   * `joystick` use RetroArch's own defaults.
   */
  inputFamily?: string | null
}

/** Remap file RetroArch loads per family; `joystick` needs none. */
export const INPUT_FAMILY_REMAPS: Record<string, string> = {
  spinner: 'oneirodex-spinner.rmp',
  lightgun: 'oneirodex-lightgun.rmp',
  trackball: 'oneirodex-trackball.rmp',
}

/**
 * Extra RetroArch arguments for a control family. Returns `[]` for joystick,
 * an unknown word or nothing at all — the companion never invents a binding
 * it was not told about.
 */
export function inputFamilyArgs(inputFamily?: string | null): string[] {
  const key = (inputFamily || '').trim().toLowerCase()
  const remap = INPUT_FAMILY_REMAPS[key]
  return remap ? ['--appendconfig', `input_remapping_path=${remap}`] : []
}

/**
 * Wave 19 — stage companion `.cht` only for RetroArch surfaces.
 * Prefer explicit `cheat_surface === 'retroarch'`. When absent, keep prior
 * staging for console systems but never for PCWIN/PCDOS/MAC/OTHER.
 */
export function shouldStageRetroArchCheat(opts: {
  cheatSurface?: string | null
  system?: string | null
  gameUuid?: string | null
  cheatFilename?: string | null
}): boolean {
  if (!opts.gameUuid || !opts.cheatFilename) {
    return false
  }
  const surface = String(opts.cheatSurface ?? '')
    .trim()
    .toLowerCase()
  if (surface === 'retroarch') {
    return true
  }
  if (surface) {
    return false
  }
  const system = String(opts.system ?? '')
    .trim()
    .toUpperCase()
  if ((PC_PLATFORMS_NO_RETROARCH_CHEATS as readonly string[]).includes(system)) {
    return false
  }
  return true
}

/**
 * Build a human-readable companion note for RetroArch AI Service setup.
 * RetroArch expects AI Service URL configured in its own settings — we do not
 * invent fragile CLI flags here.
 */
export function buildAiServiceSetupNote(hint?: RetroArchAiTranslateHint): string | null {
  if (!hint?.enabled) {
    return null
  }
  const target = hint.targetLang || 'en'
  const urlBit = hint.serviceUrl
    ? ` Suggested service URL: ${hint.serviceUrl}.`
    : ' Point RetroArch AI Service at your local OCR/MT server.'
  return (
    `Live translate: enable RetroArch → Settings → AI Service (Image mode), ` +
    `target language “${target}”.${urlBit} Overlay only — not a permanent ROM patch.`
  )
}

export function buildRetroArchArgs(profile: RetroArchProfile): string[] {
  const args = ['-L', profile.core, profile.romPath]
  // INSP-43 — the cabinet's control family, before any caller-supplied args
  // so an explicit extraArg still wins.
  args.push(...inputFamilyArgs(profile.inputFamily))
  if (profile.extraArgs?.length) {
    args.push(...profile.extraArgs)
  }
  return args
}

/** Sanitize a cheat filename for host FS (mirrors werkzeug secure_filename loosely). */
export function safeCheatFilename(filename: string): string {
  const trimmed = (filename || '').trim().replace(/\\/g, '/')
  const base = trimmed.split('/').pop() || ''
  const cleaned = base.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^\.+/, '')
  if (!cleaned) {
    return 'cheats.cht'
  }
  return cleaned.toLowerCase().endsWith('.cht') ? cleaned : `${cleaned}.cht`
}

/**
 * Fetch a library .cht for companion staging (Wave 12 / O6).
 * Returns cheat text; callers write into RetroArch's cheats dir via host FS.
 */
export async function fetchCheatText(opts: {
  gameUuid: string
  filename: string
  apiBase?: string
  fetchImpl?: typeof fetch
}): Promise<{ ok: true; text: string } | { ok: false; error: string }> {
  const base = (opts.apiBase || '').replace(/\/$/, '')
  const url = `${base}/api/games/${encodeURIComponent(opts.gameUuid)}/cheats/${encodeURIComponent(opts.filename)}`
  const fetchFn = opts.fetchImpl || fetch
  try {
    const response = await fetchFn(url, { credentials: 'include', redirect: 'error' })
    if (!response.ok) {
      return { ok: false, error: `cheat download ${response.status}` }
    }
    const text = await response.text()
    return { ok: true, text }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

export function resolveCheatStagePath(
  cheatsDir: string,
  gameUuid: string,
  filename: string,
): string {
  const root = cheatsDir.replace(/[\\/]+$/, '')
  const safeUuid = gameUuid.replace(/[^a-zA-Z0-9_-]/g, '_')
  return `${root}/${safeUuid}/${safeCheatFilename(filename)}`
}

/**
 * Download a .cht from Oneirodex and write it under companion app_data/cheats/.
 * Reuses Tauri `write_file_bytes` (ACL allows downloads + cheats roots).
 * Gated by {@link shouldStageRetroArchCheat} when `cheatSurface` / `system` are known.
 */
export async function stageCheatFile(opts: {
  gameUuid: string
  filename: string
  apiBase?: string
  cheatsDir?: string
  cheatSurface?: string | null
  system?: string | null
  fetchImpl?: typeof fetch
}): Promise<{ ok: true; path: string } | { ok: false; error: string }> {
  if (!isTauriRuntime()) {
    return { ok: false, error: 'Companion runtime required to stage cheats' }
  }
  if (
    !shouldStageRetroArchCheat({
      cheatSurface: opts.cheatSurface,
      system: opts.system,
      gameUuid: opts.gameUuid,
      cheatFilename: opts.filename,
    })
  ) {
    return { ok: false, error: 'cheat staging skipped: not retroarch surface' }
  }
  const fetched = await fetchCheatText(opts)
  if (!fetched.ok) {
    return fetched
  }
  let cheatsDir = opts.cheatsDir
  if (!cheatsDir) {
    try {
      cheatsDir = await invoke<string>('get_app_subdir', { subdir: 'cheats' })
    } catch (err) {
      return {
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      }
    }
  }
  const path = resolveCheatStagePath(cheatsDir, opts.gameUuid, opts.filename)
  const bytes = new TextEncoder().encode(fetched.text)
  try {
    await invoke('write_file_bytes', {
      path,
      bytes: new Uint8Array(bytes),
    })
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    }
  }
  return { ok: true, path }
}

export async function launchRetroArchProfile(profile: RetroArchProfile): Promise<{
  ok: true
  cheatPath?: string
}> {
  if (!isTauriRuntime()) {
    throw new Error('RetroArch launch requires the desktop companion')
  }
  let cheatPath: string | undefined
  if (
    shouldStageRetroArchCheat({
      cheatSurface: profile.cheatSurface,
      system: profile.system,
      gameUuid: profile.gameUuid,
      cheatFilename: profile.cheatFilename,
    })
  ) {
    const staged = await stageCheatFile({
      gameUuid: profile.gameUuid!,
      filename: profile.cheatFilename!,
      apiBase: profile.apiBase,
      cheatsDir: profile.cheatsDir,
      cheatSurface: profile.cheatSurface,
      system: profile.system,
    })
    if (staged.ok) {
      cheatPath = staged.path
    }
  }
  const exe = profile.retroarchPath || 'retroarch'
  await invoke('launch_game', {
    gameUuid: `retroarch:${profile.system}`,
    exePath: exe,
    extractPath: null,
    args: buildRetroArchArgs(profile),
  })
  const note = buildAiServiceSetupNote(profile.aiTranslate)
  if (note && typeof console !== 'undefined') {
    console.info(`[Oneirodex] ${note}`)
  }
  return cheatPath ? { ok: true, cheatPath } : { ok: true }
}

/** Deck / handheld companion preset names (Wave 11). */
export const HANDHELD_PRESETS = [
  { id: 'steamdeck', label: 'Steam Deck', scale: 1, performance: 'balanced' },
  { id: 'ally', label: 'ROG Ally', scale: 1, performance: 'performance' },
  { id: 'legion', label: 'Legion Go', scale: 1.25, performance: 'balanced' },
] as const

export interface WinePrefixConfig {
  prefixPath: string
  runner?: string
  dxvk?: boolean
}

export function wineLaunchEnv(cfg: WinePrefixConfig): Record<string, string> {
  const env: Record<string, string> = {
    WINEPREFIX: cfg.prefixPath,
  }
  if (cfg.runner) {
    env.WINE = cfg.runner
  }
  if (cfg.dxvk) {
    env.DXVK_HUD = '0'
  }
  return env
}
