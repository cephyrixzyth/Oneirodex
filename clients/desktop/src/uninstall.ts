import { invoke } from '@tauri-apps/api/core'

import type { AuthStore } from './auth.js'
import type { OneirodexClient } from './api.js'
import { isTauriRuntime } from './config-store.js'
import { logCompanion } from './connect.js'
import { downloadGameArchive } from './download.js'
import { extractInstallArchive, getInstallRecord } from './install.js'
import {
  loadInstallsFromDisk,
  saveInstallsToDisk,
  type SupersededInstall,
} from './install-store.js'
import type { GameLifecycleState, LifecycleRegistry } from './lifecycle.js'
import { assertValidGameUuid } from './paths.js'

async function removeLocalPath(path: string | undefined | null): Promise<void> {
  if (!path || !isTauriRuntime()) {
    return
  }
  await invoke('remove_path', { path })
}

/**
 * Everything on disk that belongs to the generation an update replaced, minus
 * anything the current install still uses.
 */
function supersededPaths(
  superseded: SupersededInstall | null | undefined,
  inUse: Array<string | null | undefined> = [],
): string[] {
  if (!superseded) {
    return []
  }
  const live = new Set(inUse.filter(Boolean))
  return [
    superseded.extractPath ? `${superseded.extractPath}.staging` : null,
    superseded.extractPath,
    superseded.archivePath,
    superseded.retainedPath,
  ].filter((path): path is string => Boolean(path) && !live.has(path as string))
}

/**
 * Remove the superseded generation after the record that no longer points at it
 * is already saved. Best effort by design: a failure can only leave an
 * unreferenced copy behind, and must never undo or fail the operation that
 * triggered it.
 */
async function removeSupersededBestEffort(
  superseded: SupersededInstall | null | undefined,
  inUse: Array<string | null | undefined>,
): Promise<void> {
  for (const path of supersededPaths(superseded, inUse)) {
    try {
      await removeLocalPath(path)
    } catch (error) {
      logCompanion(
        'uninstall',
        `could not remove superseded install file: ${error instanceof Error ? error.message : String(error)}`,
      )
    }
  }
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
  if (record && removeArchive) {
    // Nothing is kept, so nothing is copied: a snapshot here would cost a full
    // extra copy of the game, could fail on a locked file or a full disk, and
    // would be orphaned the moment the record is dropped.
    //
    // The order matters. The record is the only thing that remembers these paths,
    // so it goes last: a removal that fails part way (a locked exe, an antivirus
    // scan) throws with the record still in place, the registry still on
    // `installed`, and a second Uninstall simply tries again. Every removal is a
    // no-op for a path that is already gone.
    if (record.extractPath) {
      // Update staging dirs may remain after a failed rename — clean them too.
      await removeLocalPath(`${record.extractPath}.staging`)
      if (state !== 'downloaded') await removeLocalPath(record.extractPath)
    }
    await removeLocalPath(record.archivePath)
    // An earlier archive-retaining uninstall (or a reinstall from its snapshot)
    // left a snapshot behind; this is the "remove everything" path.
    await removeLocalPath(record.retainedPath)
    // The generation an update replaced is only reachable through this record too.
    for (const path of supersededPaths(record.superseded)) {
      await removeLocalPath(path)
    }
    const installs = await loadInstallsFromDisk()
    delete installs[gameUuid]
    await saveInstallsToDisk(installs)
  } else if (record) {
    // Archive-retaining uninstall: preserve the complete merged install,
    // including game-local saves. Archive retention alone cannot reconstruct a
    // base game plus later patch packs.
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

    // The snapshot is recorded before the working files go: the record is what
    // makes the snapshot reachable, so a crash in between keeps both copies.
    const installs = await loadInstallsFromDisk()
    installs[gameUuid] = {
      ...record,
      retainedPath,
      pendingUninstall: true,
      exePath: null,
      superseded: null,
    }
    await saveInstallsToDisk(installs)
    if (state !== 'downloaded') await removeLocalPath(record.extractPath)
    // The snapshot above is the complete current install; the generation an
    // earlier update replaced is no longer needed.
    await removeSupersededBestEffort(record.superseded, [
      record.extractPath,
      record.archivePath,
      retainedPath,
    ])
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
  // Keep the generation this update replaces — a file the new archive overwrote
  // stays recoverable there — but only that one: the generation it replaced
  // earlier is removed once the new record is saved, so repeated updates never
  // pile up full copies of the game.
  const superseded: SupersededInstall = {
    archivePath: existing.archivePath,
    extractPath: existing.extractPath,
    ...(existing.retainedPath ? { retainedPath: existing.retainedPath } : {}),
  }
  await saveInstallsToDisk({
    ...(await loadInstallsFromDisk()),
    [gameUuid]: { ...extracted, superseded },
  })
  await removeSupersededBestEffort(existing.superseded, [
    extracted.extractPath,
    extracted.archivePath,
    superseded.extractPath,
    superseded.archivePath,
    superseded.retainedPath,
  ])

  if (needsForcedUpdateState) {
    registry.signalUpdateAvailable(gameUuid)
  }
  return registry.apply(gameUuid, 'update')
}
