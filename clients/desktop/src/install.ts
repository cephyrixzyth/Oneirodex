import { invoke } from '@tauri-apps/api/core'

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

export async function getInstallRecord(gameUuid: string): Promise<GameInstallRecord | null> {
  const installs = await loadInstallsFromDisk()

  return installs[gameUuid] ?? null
}

export async function extractInstallArchive(
  gameUuid: string,

  record: GameInstallRecord,
  options: { persist?: boolean } = {},
): Promise<GameInstallRecord> {
  if (!isTauriRuntime()) {
    return record
  }

  const result = record.retainedPath
    ? await invoke<ExtractZipResult>('restore_install_snapshot', {
        from: record.retainedPath,
        to: `${record.extractPath}.reinstall-${crypto.randomUUID()}`,
      })
    : await invoke<ExtractZipResult>('extract_zip_archive', {
        archivePath: record.archivePath,

        destDir: record.extractPath,
      })

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
): Promise<GameLifecycleState> {
  assertValidGameUuid(gameUuid)

  if (registry.get(gameUuid) !== 'downloaded') {
    throw new Error(`Game ${gameUuid} is not in downloaded state`)
  }

  const record = await getInstallRecord(gameUuid)

  if (!record) {
    throw new Error(`No local archive found for ${gameUuid}`)
  }

  await extractInstallArchive(gameUuid, record)

  return registry.apply(gameUuid, 'install')
}
