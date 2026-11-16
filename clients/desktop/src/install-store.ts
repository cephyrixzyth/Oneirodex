import { invoke } from '@tauri-apps/api/core'

import { isTauriRuntime } from './config-store.js'

/**
 * The generation an update replaced. It is kept for exactly one more update (or
 * until the game is uninstalled) so a file the new archive overwrote can still be
 * recovered, and is then removed — never more than one superseded copy on disk.
 */
export interface SupersededInstall {
  archivePath: string
  extractPath: string
  retainedPath?: string | null
}

export interface GameInstallRecord {
  archivePath: string
  extractPath: string
  exePath?: string | null
  retainedPath?: string | null
  pendingUninstall?: boolean
  superseded?: SupersededInstall | null
}

export interface InstallsFile {
  installs: Record<string, GameInstallRecord>
}

interface RawSupersededInstall {
  archive_path: string
  extract_path: string
  retained_path?: string | null
}

interface RawInstallRecord {
  archive_path: string
  extract_path: string
  exe_path?: string | null
  retained_path?: string | null
  pending_uninstall?: boolean
  superseded?: RawSupersededInstall | null
}

interface RawInstallsFile {
  installs?: Record<string, RawInstallRecord>
}

function toRawInstalls(
  installs: Record<string, GameInstallRecord>,
): Record<string, RawInstallRecord> {
  return Object.fromEntries(
    Object.entries(installs).map(([gameUuid, record]) => [
      gameUuid,
      {
        archive_path: record.archivePath,
        extract_path: record.extractPath,
        exe_path: record.exePath ?? null,
        ...(record.retainedPath ? { retained_path: record.retainedPath } : {}),
        ...(record.pendingUninstall ? { pending_uninstall: true } : {}),
        ...(record.superseded
          ? {
              superseded: {
                archive_path: record.superseded.archivePath,
                extract_path: record.superseded.extractPath,
                ...(record.superseded.retainedPath
                  ? { retained_path: record.superseded.retainedPath }
                  : {}),
              },
            }
          : {}),
      },
    ]),
  )
}

function fromRawInstalls(
  installs: Record<string, RawInstallRecord> | undefined,
): Record<string, GameInstallRecord> {
  if (!installs) {
    return {}
  }

  return Object.fromEntries(
    Object.entries(installs).map(([gameUuid, record]) => [
      gameUuid,
      {
        archivePath: record.archive_path,
        extractPath: record.extract_path,
        exePath: record.exe_path ?? null,
        ...(record.retained_path ? { retainedPath: record.retained_path } : {}),
        ...(record.pending_uninstall ? { pendingUninstall: true } : {}),
        ...(record.superseded
          ? {
              superseded: {
                archivePath: record.superseded.archive_path,
                extractPath: record.superseded.extract_path,
                ...(record.superseded.retained_path
                  ? { retainedPath: record.superseded.retained_path }
                  : {}),
              },
            }
          : {}),
      },
    ]),
  )
}

const loadedSnapshots = new WeakMap<
  Record<string, GameInstallRecord>,
  Record<string, GameInstallRecord>
>()
let saveQueue: Promise<void> = Promise.resolve()

function cloneInstalls(
  installs: Record<string, GameInstallRecord>,
): Record<string, GameInstallRecord> {
  return structuredClone(installs)
}

export async function loadInstallsFromDisk(): Promise<Record<string, GameInstallRecord>> {
  if (!isTauriRuntime()) {
    return {}
  }

  const raw = await invoke<RawInstallsFile>('load_installs')
  const installs = fromRawInstalls(raw.installs)
  loadedSnapshots.set(installs, cloneInstalls(installs))
  return installs
}

export async function saveInstallsToDisk(
  installs: Record<string, GameInstallRecord>,
): Promise<void> {
  if (!isTauriRuntime()) {
    return
  }

  const baseline = loadedSnapshots.get(installs)
  if (!baseline) {
    throw new Error('Install records must be loaded before they can be saved')
  }
  const desired = cloneInstalls(installs)
  const save = saveQueue.then(async () => {
    const raw = await invoke<RawInstallsFile>('load_installs')
    const latest = fromRawInstalls(raw.installs)
    const keys = new Set([...Object.keys(baseline), ...Object.keys(desired)])
    for (const key of keys) {
      const wasPresent = Object.prototype.hasOwnProperty.call(baseline, key)
      const isPresent = Object.prototype.hasOwnProperty.call(desired, key)
      if (!isPresent) {
        if (wasPresent) delete latest[key]
        continue
      }
      if (!wasPresent || JSON.stringify(baseline[key]) !== JSON.stringify(desired[key])) {
        latest[key] = desired[key]
      }
    }
    await invoke('save_installs', {
      installsFile: { installs: toRawInstalls(latest) },
    })
    loadedSnapshots.set(installs, desired)
  })
  saveQueue = save.catch(() => undefined)
  await save
}
