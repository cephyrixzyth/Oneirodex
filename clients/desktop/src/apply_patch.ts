/**
 * Companion ROM patch apply (Flips IPS/BPS) — Phase 3.
 * Stages under app_data/patches/ (ACL-safe); unit tests mock Flips invoke.
 */

import { invoke } from '@tauri-apps/api/core'

import { isTauriRuntime } from './config-store.js'
import { joinUrl } from './paths.js'
import { checkDownloadRedirectUrl } from './transport-policy.js'

/** Keep patch staging bounded before the response is copied into a Tauri IPC array. */
export const MAX_PATCH_DOWNLOAD_BYTES = 256 * 1024 * 1024

function declaredContentLength(response: Response): number | null {
  const value = response.headers?.get?.('content-length')?.trim()
  if (!value || !/^\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null
}

function patchSizeLimitLabel(maxBytes: number): string {
  const mebibyte = 1024 * 1024
  return maxBytes >= mebibyte && maxBytes % mebibyte === 0
    ? `${maxBytes / mebibyte} MiB`
    : `${maxBytes} byte${maxBytes === 1 ? '' : 's'}`
}

/** Send bounded chunks to native storage while enforcing the cumulative patch limit. */
export async function streamBoundedPatchResponse(
  response: Response,
  writeChunk: (chunk: Uint8Array) => Promise<void>,
  maxBytes = MAX_PATCH_DOWNLOAD_BYTES,
): Promise<number> {
  // Keep the exported helper from weakening production's ceiling if a caller
  // supplies a non-finite or larger value; smaller limits remain useful to tests.
  const byteLimit = Number.isFinite(maxBytes)
    ? Math.min(MAX_PATCH_DOWNLOAD_BYTES, Math.max(0, Math.floor(maxBytes)))
    : MAX_PATCH_DOWNLOAD_BYTES
  const limitLabel = patchSizeLimitLabel(byteLimit)
  const declared = declaredContentLength(response)
  if (declared !== null && declared > byteLimit) {
    try {
      await response.body?.cancel()
    } catch {
      // A response stub or an already-closed stream may not be cancellable.
    }
    throw new Error(`Patch download exceeds the ${limitLabel} limit`)
  }

  const body = response.body
  if (!body) throw new Error('Patch response was empty')

  const reader = body.getReader()
  let bytesReceived = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (!value?.byteLength) continue
      if (value.byteLength > byteLimit - bytesReceived) {
        throw new Error(`Patch download exceeds the ${limitLabel} limit`)
      }
      bytesReceived += value.byteLength
      for (let offset = 0; offset < value.byteLength; offset += 1024 * 1024) {
        await writeChunk(value.subarray(offset, offset + 1024 * 1024))
      }
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined)
    throw error
  } finally {
    reader.releaseLock()
  }

  if (!bytesReceived || (declared !== null && declared !== bytesReceived)) {
    throw new Error('Patch response was empty or incomplete')
  }
  return bytesReceived
}

export function safePatchFilename(filename: string): string {
  const trimmed = (filename || '').trim().replace(/\\/g, '/')
  const base = trimmed.split('/').pop() || ''
  const cleaned = base.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^\.+/, '')
  if (!cleaned) {
    return 'patch'
  }
  return cleaned
}

export function resolvePatchStageDir(patchesDir: string, gameUuid: string): string {
  const root = patchesDir.replace(/[\\/]+$/, '')
  const safeUuid = gameUuid.replace(/[^a-zA-Z0-9_-]/g, '_')
  return `${root}/${safeUuid}`
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
  const fetchFn = opts.fetchImpl || fetch
  try {
    const headers: Record<string, string> = {}
    if (opts.authHeader) {
      headers.Authorization = opts.authHeader
    }
    const initiation = await fetchFn(
      `${base}/api/downloads/games/${encodeURIComponent(opts.gameUuid)}`,
      {
        method: 'POST',
        credentials: 'omit',
        redirect: 'error',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'extra', version_uuid: opts.patchUuid }),
      },
    )
    if (initiation.url) {
      const check = checkDownloadRedirectUrl(initiation.url)
      if (!check.ok) return { ok: false, error: check.message }
    }
    if (!initiation.ok) {
      return { ok: false, error: `patch request ${initiation.status}` }
    }
    const initiated = await initiation.json()
    if (initiated?.ok !== true) {
      return { ok: false, error: initiated?.error || 'patch request was rejected' }
    }
    const streamPath = initiated?.stream_url
    if (typeof streamPath !== 'string' || !streamPath.startsWith('/')) {
      return { ok: false, error: 'patch request returned an invalid stream URL' }
    }
    const response = await fetchFn(joinUrl(base, streamPath), {
      credentials: 'omit',
      redirect: 'error',
      headers,
    })
    if (response.url) {
      const check = checkDownloadRedirectUrl(response.url)
      if (!check.ok) return { ok: false, error: check.message }
    }
    if (!response.ok) {
      return { ok: false, error: `patch download ${response.status}` }
    }
    let path = ''
    try {
      await streamBoundedPatchResponse(response, async (chunk) => {
        if (!path) {
          const patchesDir = await getPatchesDir()
          const stageDir = resolvePatchStageDir(patchesDir + '/.staging', opts.gameUuid)
          const name = safePatchFilename(opts.filename || opts.patchUuid)
          path = `${stageDir}/${crypto.randomUUID()}-${name}`
          await invoke('write_file_bytes', { path, bytes: chunk })
        } else {
          await invoke('append_file_bytes', { path, bytes: chunk })
        }
      })
    } catch (error) {
      if (path) await invoke('remove_path', { path }).catch(() => undefined)
      throw error
    }
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
