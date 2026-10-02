import { invoke } from '@tauri-apps/api/core'

import type { GameVersionItem, InitiateDownloadResponse } from '@oneirodex/api-client'

import type { AuthStore } from './auth.js'
import type { OneirodexClient } from './api.js'
import { escapeHtml } from './html.js'
import { isTauriRuntime } from './config-store.js'
import {
  loadInstallsFromDisk,
  saveInstallsToDisk,
  type GameInstallRecord,
} from './install-store.js'
import type { GameLifecycleState, LifecycleRegistry } from './lifecycle.js'
import {
  assertValidGameUuid,
  buildDownloadStreamPath,
  buildLocalArchiveName,
  buildLocalInstallDirName,
  joinUrl,
} from './paths.js'
import { checkDownloadRedirectUrl } from './transport-policy.js'

export interface DownloadProgress {
  bytesReceived: number
  totalBytes: number | null
}

export type DownloadProgressCallback = (progress: DownloadProgress) => void

async function getDownloadsDir(): Promise<string> {
  if (!isTauriRuntime()) {
    return '/tmp/oneirodex/downloads'
  }
  return invoke<string>('get_app_subdir', { subdir: 'downloads' })
}

export async function getInstallsDir(): Promise<string> {
  if (!isTauriRuntime()) {
    return '/tmp/oneirodex/installs'
  }
  return invoke<string>('get_app_subdir', { subdir: 'installs' })
}

/** Throws on a game id (or generation) that is not a plain path segment. */
export function resolveArchivePath(
  downloadsDir: string,
  gameUuid: string,
  generation?: string,
): string {
  return `${downloadsDir.replace(/[/\\]+$/, '')}/${buildLocalArchiveName(gameUuid, generation)}`
}

/** Throws on a game id (or generation) that is not a plain path segment. */
export function resolveExtractPath(
  installsDir: string,
  gameUuid: string,
  generation?: string,
): string {
  return `${installsDir.replace(/[/\\]+$/, '')}/${buildLocalInstallDirName(gameUuid, generation)}`
}

export async function initiateDownloadRequest(
  api: OneirodexClient,
  gameUuid: string,
  options: { kind?: 'base' | 'update' | 'extra'; versionUuid?: string } = {},
): Promise<InitiateDownloadResponse> {
  return api.downloads.initiateGameDownload(gameUuid, options)
}

/**
 * An https server may answer with a redirect, and `fetch` follows it on its own.
 * What is checked is the URL it ended on (`response.url`), against the same
 * http://-only-on-your-own-network rule as the server URL. A plain `http://` leg
 * in the middle of a redirect chain is invisible here (`fetch` reports only the
 * last URL, and `redirect: 'manual'` hides the Location header), so the server is
 * expected to stream `/download_zip/<id>` itself or redirect straight to https:
 * an archive rewritten in transit is extracted into `installs/` and launched.
 * (`fetch` drops the Authorization header on a cross-origin hop, so the token is
 * safe either way.) Mocks and some runtimes leave `url` empty — nothing to check
 * then.
 */
function assertDownloadFinalUrlAllowed(response: Response): void {
  if (!response.url) {
    return
  }
  const check = checkDownloadRedirectUrl(response.url)
  if (check.ok) {
    return
  }
  // Stop the transfer; nothing has been written to disk yet.
  try {
    void Promise.resolve(response.body?.cancel()).catch(() => undefined)
  } catch {
    // No stream to cancel (a stub response, or one already locked).
  }
  throw new Error(check.message)
}

export async function fetchDownloadStream(
  auth: AuthStore,
  streamPath: string,
  options: {
    fetchImpl?: typeof fetch
    onProgress?: DownloadProgressCallback
  } = {},
): Promise<ArrayBuffer> {
  const authHeader = auth.authorizationHeader()
  if (!authHeader) {
    throw new Error('Not authenticated')
  }

  const fetchImpl = options.fetchImpl ?? fetch
  const response = await fetchImpl(joinUrl(auth.getBaseUrl(), streamPath), {
    method: 'GET',
    headers: {
      Authorization: authHeader,
    },
  })
  assertDownloadFinalUrlAllowed(response)

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Download failed with HTTP ${response.status}`)
  }

  const totalHeader = response.headers.get('content-length')
  const totalBytes = totalHeader ? Number.parseInt(totalHeader, 10) : null
  const body = response.body

  if (!body || !options.onProgress) {
    return response.arrayBuffer()
  }

  const reader = body.getReader()
  const chunks: Uint8Array[] = []
  let bytesReceived = 0

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    if (value) {
      chunks.push(value)
      bytesReceived += value.byteLength
      options.onProgress({ bytesReceived, totalBytes })
    }
  }

  const merged = new Uint8Array(bytesReceived)
  let offset = 0
  for (const chunk of chunks) {
    merged.set(chunk, offset)
    offset += chunk.byteLength
  }
  return merged.buffer
}

/** Stream a download directly to disk (avoids buffering the full zip in RAM). */
export async function streamDownloadToFile(
  auth: AuthStore,
  streamPath: string,
  archivePath: string,
  options: {
    fetchImpl?: typeof fetch
    onProgress?: DownloadProgressCallback
  } = {},
): Promise<void> {
  const authHeader = auth.authorizationHeader()
  if (!authHeader) {
    throw new Error('Not authenticated')
  }

  const fetchImpl = options.fetchImpl ?? fetch
  const response = await fetchImpl(joinUrl(auth.getBaseUrl(), streamPath), {
    method: 'GET',
    headers: {
      Authorization: authHeader,
    },
  })
  assertDownloadFinalUrlAllowed(response)

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Download failed with HTTP ${response.status}`)
  }

  const totalHeader = response.headers.get('content-length')
  const totalBytes = totalHeader ? Number.parseInt(totalHeader, 10) : null
  const body = response.body

  if (!isTauriRuntime()) {
    return
  }

  // Truncate / create destination.
  await invoke('write_file_bytes', { path: archivePath, bytes: new Uint8Array(0) })

  if (!body) {
    const bytes = new Uint8Array(await response.arrayBuffer())
    if (bytes.byteLength > 0) {
      await invoke('append_file_bytes', { path: archivePath, bytes })
    }
    options.onProgress?.({ bytesReceived: bytes.byteLength, totalBytes })
    return
  }

  const reader = body.getReader()
  let bytesReceived = 0
  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    if (value) {
      await invoke('append_file_bytes', { path: archivePath, bytes: value })
      bytesReceived += value.byteLength
      options.onProgress?.({ bytesReceived, totalBytes })
    }
  }
}

export async function writeDownloadArchive(archivePath: string, bytes: ArrayBuffer): Promise<void> {
  if (!isTauriRuntime()) {
    return
  }
  await invoke('write_file_bytes', {
    path: archivePath,
    bytes: new Uint8Array(bytes),
  })
}

export async function persistInstallRecord(
  gameUuid: string,
  record: GameInstallRecord,
): Promise<void> {
  const installs = await loadInstallsFromDisk()
  installs[gameUuid] = record
  await saveInstallsToDisk(installs)
}

export async function downloadGameArchive(
  api: OneirodexClient,
  auth: AuthStore,
  gameUuid: string,
  options: {
    fetchImpl?: typeof fetch
    onProgress?: DownloadProgressCallback
    kind?: 'base' | 'update' | 'extra'
    versionUuid?: string
    /** Isolated update generation; never overwrite the working archive/record. */
    generation?: string
  } = {},
): Promise<GameInstallRecord> {
  // The id becomes `{id}.zip` and `installs/{id}`; refuse anything that is not a
  // plain path segment before the server is asked for anything.
  assertValidGameUuid(gameUuid)
  const initiated = await initiateDownloadRequest(api, gameUuid, {
    kind: options.kind,
    versionUuid: options.versionUuid,
  })
  const streamPath = initiated.stream_url || buildDownloadStreamPath(initiated.download_id)

  const downloadsDir = await getDownloadsDir()
  const archivePath = resolveArchivePath(downloadsDir, gameUuid, options.generation)

  if (isTauriRuntime()) {
    await streamDownloadToFile(auth, streamPath, archivePath, options)
  } else {
    const bytes = await fetchDownloadStream(auth, streamPath, options)
    await writeDownloadArchive(archivePath, bytes)
  }

  const installsDir = await getInstallsDir()
  const record: GameInstallRecord = {
    archivePath,
    extractPath: resolveExtractPath(installsDir, gameUuid, options.generation),
  }
  if (!options.generation) await persistInstallRecord(gameUuid, record)
  return record
}

export async function kickoffDownload(
  api: OneirodexClient,
  auth: AuthStore,
  registry: LifecycleRegistry,
  gameUuid: string,
  options: {
    fetchImpl?: typeof fetch
    onProgress?: DownloadProgressCallback
    kind?: 'base' | 'update' | 'extra'
    versionUuid?: string
  } = {},
): Promise<GameLifecycleState> {
  assertValidGameUuid(gameUuid)
  if (registry.get(gameUuid) !== 'not_downloaded') {
    throw new Error(`Game ${gameUuid} is not in not_downloaded state`)
  }

  await downloadGameArchive(api, auth, gameUuid, options)
  return registry.apply(gameUuid, 'download')
}

export async function pickDownloadVersion(
  api: OneirodexClient,
  gameUuid: string,
): Promise<{ kind: 'base' | 'update' | 'extra'; versionUuid?: string }> {
  try {
    const payload = await api.downloads.listGameVersions(gameUuid)
    const versions = payload.versions || []
    if (versions.length <= 1) {
      return { kind: 'base' }
    }
    const chosen = await promptForDownloadVersion(gameUuid, versions)
    if (!chosen) {
      return { kind: 'base' }
    }
    if (chosen.kind === 'update' || chosen.kind === 'extra') {
      return { kind: chosen.kind, versionUuid: chosen.uuid }
    }
    return { kind: 'base' }
  } catch {
    return { kind: 'base' }
  }
}

/**
 * In-DOM version picker. Replaces `window.prompt()`: a synchronous prompt blocks
 * the Tauri webview event loop, cannot be styled or keyboard-driven, and reads
 * as a browser artefact in a native window. This renders a small modal overlay
 * in the same hand-built style as the rest of `app.ts` — a radiogroup of
 * versions, arrow-key navigation, Enter to confirm, Escape / backdrop to cancel.
 *
 * Resolves with the chosen version, or `null` when dismissed or when there is no
 * DOM to render into (tests, non-webview runs) — callers treat `null` as "use
 * the base version".
 */
export function promptForDownloadVersion(
  gameUuid: string,
  versions: GameVersionItem[],
): Promise<GameVersionItem | null> {
  if (typeof document === 'undefined' || !document.body || versions.length === 0) {
    return Promise.resolve(null)
  }

  return new Promise<GameVersionItem | null>((resolve) => {
    const defaultIndex = Math.max(
      versions.findIndex((version) => version.is_default),
      0,
    )
    let selectedIndex = defaultIndex
    let settled = false

    const overlay = document.createElement('div')
    overlay.className = 'od-version-overlay'
    overlay.setAttribute('role', 'dialog')
    overlay.setAttribute('aria-modal', 'true')
    overlay.setAttribute('aria-label', 'Choose a version to download')

    const panel = document.createElement('div')
    panel.className = 'od-version-panel'
    // Static shell; the one dynamic value (game id) is escaped like every other
    // innerHTML site in this client — see html.ts.
    panel.innerHTML =
      `<h3>Choose a version to download</h3>` + `<p class="muted">${escapeHtml(gameUuid)}</p>`

    const group = document.createElement('div')
    group.className = 'od-version-list'
    group.setAttribute('role', 'radiogroup')

    const options: HTMLButtonElement[] = versions.map((version, index) => {
      const option = document.createElement('button')
      option.type = 'button'
      option.className = 'od-version-option'
      option.setAttribute('role', 'radio')
      const kindLabel = version.kind ? `[${version.kind}] ` : ''
      // textContent — never parsed as markup, so server-supplied labels are inert.
      option.textContent = `${kindLabel}${version.label}`
      option.addEventListener('click', () => {
        selectedIndex = index
        syncSelection()
      })
      option.addEventListener('dblclick', () => finish(versions[index] ?? null))
      return option
    })
    for (const option of options) {
      group.append(option)
    }

    const actions = document.createElement('div')
    actions.className = 'od-version-actions'
    const cancelButton = document.createElement('button')
    cancelButton.type = 'button'
    cancelButton.className = 'od-version-cancel'
    cancelButton.textContent = 'Cancel'
    cancelButton.addEventListener('click', () => finish(null))
    const confirmButton = document.createElement('button')
    confirmButton.type = 'button'
    confirmButton.className = 'od-version-confirm'
    confirmButton.textContent = 'Download'
    confirmButton.addEventListener('click', () => finish(versions[selectedIndex] ?? null))
    actions.append(cancelButton, confirmButton)

    panel.append(group, actions)
    overlay.append(panel)

    overlay.addEventListener('mousedown', (event) => {
      if (event.target === overlay) {
        finish(null)
      }
    })
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        finish(null)
      } else if (event.key === 'Enter') {
        event.preventDefault()
        finish(versions[selectedIndex] ?? null)
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        const delta = event.key === 'ArrowDown' ? 1 : -1
        selectedIndex = (selectedIndex + delta + versions.length) % versions.length
        syncSelection()
        options[selectedIndex]?.focus()
      }
    }

    function syncSelection(): void {
      options.forEach((option, index) => {
        const active = index === selectedIndex
        option.setAttribute('aria-checked', active ? 'true' : 'false')
        option.classList.toggle('is-selected', active)
        option.tabIndex = active ? 0 : -1
      })
    }

    function finish(result: GameVersionItem | null): void {
      if (settled) {
        return
      }
      settled = true
      document.removeEventListener('keydown', onKeyDown, true)
      overlay.remove()
      resolve(result)
    }

    document.addEventListener('keydown', onKeyDown, true)
    document.body.append(overlay)
    syncSelection()
    options[selectedIndex]?.focus()
  })
}
