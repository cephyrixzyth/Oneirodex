import { invoke } from '@tauri-apps/api/core'

import type { OneirodexClient } from './api.js'
import { isTauriRuntime } from './config-store.js'
import { getInstallRecord } from './install.js'
import {
  loadInstallsFromDisk,
  saveInstallsToDisk,
  type GameInstallRecord,
} from './install-store.js'
import type { GameLifecycleState } from './lifecycle.js'
import { watchPlaySession, type PlaySessionWatcher } from './playtime-session.js'

interface LaunchGameResult {
  pid: number
  exe_path: string
  resolved_exe_path?: string | null
}

const activeWatchers = new Map<string, PlaySessionWatcher>()

export function canLaunchGame(state: GameLifecycleState): boolean {
  return state === 'installed' || state === 'update_available'
}

export async function kickoffLaunch(
  api: OneirodexClient,
  gameUuid: string,
): Promise<{ pid: number; sessionId: number }> {
  if (!isTauriRuntime()) {
    throw new Error('Launch is only available in the desktop app')
  }

  const record = await getInstallRecord(gameUuid)
  if (!record) {
    throw new Error(`No local install found for ${gameUuid}`)
  }

  const launchResult = await invoke<LaunchGameResult>('launch_game', {
    gameUuid,
    exePath: record.exePath ?? null,
    extractPath: record.extractPath,
  })

  if (launchResult.resolved_exe_path) {
    await persistResolvedExePath(gameUuid, record, launchResult.resolved_exe_path)
  }

  const session = await api.playtime.startSession({
    game_uuid: gameUuid,
    client: 'desktop',
  })

  const sessionId = session.id
  if (typeof sessionId !== 'number') {
    throw new Error('Playtime session did not return an id')
  }

  const existing = activeWatchers.get(gameUuid)
  if (existing) {
    await existing.stop()
    activeWatchers.delete(gameUuid)
  }

  activeWatchers.set(gameUuid, watchPlaySession(api, launchResult.pid, sessionId))

  return { pid: launchResult.pid, sessionId }
}

async function persistResolvedExePath(
  gameUuid: string,
  record: GameInstallRecord,
  exePath: string,
): Promise<void> {
  // Spread the record: it also carries `retainedPath`, `pendingUninstall` and
  // `superseded`, and rebuilding it from three fields drops the pointers to those
  // files and orphans them.
  const updated: GameInstallRecord = { ...record, exePath }
  const installs = await loadInstallsFromDisk()
  installs[gameUuid] = updated
  await saveInstallsToDisk(installs)
}

export async function stopLaunchWatcher(gameUuid: string): Promise<void> {
  const watcher = activeWatchers.get(gameUuid)
  if (!watcher) {
    return
  }
  await watcher.stop()
  activeWatchers.delete(gameUuid)
}
