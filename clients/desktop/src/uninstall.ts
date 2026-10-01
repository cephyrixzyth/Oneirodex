import { invoke } from '@tauri-apps/api/core'

import type { AuthStore } from './auth.js'
import type { OneirodexClient } from './api.js'
import { isTauriRuntime } from './config-store.js'
import { downloadGameArchive } from './download.js'
import { extractInstallArchive, getInstallRecord } from './install.js'
import { loadInstallsFromDisk, saveInstallsToDisk } from './install-store.js'
import type { GameLifecycleState, LifecycleRegistry } from './lifecycle.js'
import { assertValidGameUuid } from './paths.js'

async function removeLocalPath(path: string | undefined | null): Promise<void> {
  if (!path || !isTauriRuntime()) {
    return
  }
  await invoke('remove_path', { path })
}

export async function kickoffUninstall(
  registry: LifecycleRegistry,
  gameUuid: string,
  options: { removeArchive?: boolean } = {},
): Promise<GameLifecycleState> {
  assertValidGameUuid(gameUuid)
  const state = registry.get(gameUuid)
  if (state !== 'downloaded' && state !== 'installed' && state !== 'update_available') {
    throw new Error(`Game ${gameUuid} cannot be uninstalled from state ${state}`)
  }

  const removeArchive = options.removeArchive ?? true
  const record = await getInstallRecord(gameUuid)
  if (record) {
    // Preserve the complete merged install, including game-local saves. Archive
    // retention alone cannot reconstruct a base game plus later patch packs.
    const retainedPath =
      state === 'downloaded' || record.pendingUninstall
        ? record.retainedPath
        : isTauriRuntime()
          ? await invoke<string | null>('preserve_install_files', {
              path: record.extractPath,
              backupPath: `${record.extractPath}.uninstalled-${crypto.randomUUID()}`,
            })
          : record.retainedPath
    // Update staging dirs may remain after a failed rename — clean them too.
    if (record.extractPath) {
      await removeLocalPath(`${record.extractPath}.staging`)
    }
    if (removeArchive) {
      await removeLocalPath(record.archivePath)
    }

    const installs = await loadInstallsFromDisk()
    if (removeArchive) {
      delete installs[gameUuid]
    } else {
      installs[gameUuid] = { ...record, retainedPath, pendingUninstall: true, exePath: null }
    }
    await saveInstallsToDisk(installs)
    if (state !== 'downloaded') await removeLocalPath(record.extractPath)
  }

  let next =
    !removeArchive && state === 'downloaded' ? state : registry.apply(gameUuid, 'uninstall')
  // Default uninstall removes the archive — `downloaded` without files is a dead end.
  if (removeArchive && next === 'downloaded') {
    next = registry.apply(gameUuid, 'uninstall')
  }
  return next
}

export async function kickoffUpdate(
  api: OneirodexClient,
  auth: AuthStore,
  registry: LifecycleRegistry,
  gameUuid: string,
  options: {
    fetchImpl?: typeof fetch
    onProgress?: (progress: { bytesReceived: number; totalBytes: number | null }) => void
    kind?: 'base' | 'update' | 'extra'
    versionUuid?: string
  } = {},
): Promise<GameLifecycleState> {
  assertValidGameUuid(gameUuid)
  const state = registry.get(gameUuid)
  const applyingPack =
    Boolean(options.versionUuid) || options.kind === 'update' || options.kind === 'extra'
  const needsForcedUpdateState =
    state !== 'update_available' &&
    applyingPack &&
    (state === 'installed' || state === 'downloaded')

  if (state !== 'update_available' && !needsForcedUpdateState) {
    throw new Error(`Game ${gameUuid} is not in update_available state`)
  }

  const existing = await getInstallRecord(gameUuid)
  if (!existing) throw new Error('No working install record found for update')
  if (existing.pendingUninstall) throw new Error('Finish uninstall or reinstall before updating')
  // Each attempt has its own files. The atomic registry replacement is the
  // commit point; a crash before it leaves the previous install selected.
  const record = await downloadGameArchive(api, auth, gameUuid, {
    fetchImpl: options.fetchImpl,
    onProgress: options.onProgress,
    kind: options.kind,
    versionUuid: options.versionUuid,
    generation: `update-${crypto.randomUUID()}`,
  })

  const extracted = await extractInstallArchive(gameUuid, record, { persist: false })
  if (isTauriRuntime() && state !== 'downloaded') {
    // Carry files absent from the update (including saves and base files in
    // patch packs). Colliding files remain recoverable in the old directory.
    await invoke('retain_install_files', {
      from: existing.extractPath,
      to: extracted.extractPath,
    })
    if (!extracted.exePath && existing.exePath?.startsWith(`${existing.extractPath}/`)) {
      extracted.exePath =
        extracted.extractPath + existing.exePath.slice(existing.extractPath.length)
    }
  }
  await saveInstallsToDisk({
    ...(await loadInstallsFromDisk()),
    [gameUuid]: extracted,
  })

  if (needsForcedUpdateState) {
    registry.signalUpdateAvailable(gameUuid)
  }
  return registry.apply(gameUuid, 'update')
}
