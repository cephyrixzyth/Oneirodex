import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import { isTauriRuntime } from './config-store.js'

import {
  loadInstallsFromDisk,
  saveInstallsToDisk,
  type GameInstallRecord,
} from './install-store.js'

import type { GameLifecycleState, LifecycleRegistry } from './lifecycle.js'
import { assertValidGameUuid } from './paths.js'

interface ExtractZipResult {
  extract_path: string

  exe_path?: string | null
}

export interface ExtractZipProgress {
  bytes_extracted: number
  total_bytes: number
}

interface GameArchiveProgressMessage extends ExtractZipProgress {
  operation_id: string
}

export async function getInstallRecord(gameUuid: string): Promise<GameInstallRecord | null> {
  const installs = await loadInstallsFromDisk()

  return installs[gameUuid] ?? null
}

export async function extractInstallArchive(
  gameUuid: string,

  record: GameInstallRecord,
  options: {
    persist?: boolean
    operationId?: string
    onProgress?: (progress: ExtractZipProgress) => void
  } = {},
): Promise<GameInstallRecord> {
  if (!isTauriRuntime()) {
    return record
  }

  const result = record.retainedPath
    ? await invoke<ExtractZipResult>('restore_install_snapshot', {
        from: record.retainedPath,
        to: `${record.extractPath}.reinstall-${crypto.randomUUID()}`,
      })
    : await (async () => {
        const operationId = options.operationId ?? crypto.randomUUID()
        const unlisten = options.onProgress
          ? await listen<GameArchiveProgressMessage>('game-archive-progress', ({ payload }) => {
              if (payload.operation_id === operationId) {
                options.onProgress?.({
                  bytes_extracted: payload.bytes_extracted,
                  total_bytes: payload.total_bytes,
                })
              }
            })
          : undefined
        try {
          return await invoke<ExtractZipResult>('extract_zip_archive', {
            archivePath: record.archivePath,
            destDir: record.extractPath,
            operationId,
          })
        } finally {
          unlisten?.()
        }
      })()

  const updated: GameInstallRecord = {
    archivePath: record.archivePath,

    extractPath: result.extract_path,

    exePath: result.exe_path ?? null,
    ...(record.retainedPath ? { retainedPath: record.retainedPath } : {}),
  }

  if (options.persist !== false) {
    const installs = await loadInstallsFromDisk()
    installs[gameUuid] = updated
    await saveInstallsToDisk(installs)
  }

  return updated
}

export async function kickoffInstall(
  registry: LifecycleRegistry,

  gameUuid: string,
  options: {
    operationId?: string
    onProgress?: (progress: ExtractZipProgress) => void
  } = {},
): Promise<GameLifecycleState> {
  assertValidGameUuid(gameUuid)

  if (registry.get(gameUuid) !== 'downloaded') {
    throw new Error(`Game ${gameUuid} is not in downloaded state`)
  }

  const record = await getInstallRecord(gameUuid)

  if (!record) {
    throw new Error(`No local archive found for ${gameUuid}`)
  }

  await extractInstallArchive(gameUuid, record, options)

  return registry.apply(gameUuid, 'install')
}

export async function cancelInstallArchive(operationId: string): Promise<boolean> {
  return invoke<boolean>('cancel_game_archive_install', { operationId })
}
