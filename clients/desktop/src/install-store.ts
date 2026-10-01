import { invoke } from '@tauri-apps/api/core'

import { isTauriRuntime } from './config-store.js'

export interface GameInstallRecord {
  archivePath: string
  extractPath: string
  exePath?: string | null
  retainedPath?: string | null
  pendingUninstall?: boolean
}

export interface InstallsFile {
  installs: Record<string, GameInstallRecord>
}

interface RawInstallRecord {
  archive_path: string
  extract_path: string
  exe_path?: string | null
  retained_path?: string | null
  pending_uninstall?: boolean
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
      },
    ]),
  )
}

export async function loadInstallsFromDisk(): Promise<Record<string, GameInstallRecord>> {
  if (!isTauriRuntime()) {
    return {}
  }

  const raw = await invoke<RawInstallsFile>('load_installs')
  return fromRawInstalls(raw.installs)
}

export async function saveInstallsToDisk(
  installs: Record<string, GameInstallRecord>,
): Promise<void> {
  if (!isTauriRuntime()) {
    return
  }

  await invoke('save_installs', {
    installsFile: {
      installs: toRawInstalls(installs),
    },
  })
}
