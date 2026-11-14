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
import { hasNativeLaunchIdentity } from './process-status.js'
import { launchRecovery } from './launch-recovery.js'

export interface LaunchProfileOptions {
  profileBinding: string | null
  current: () => boolean
  canReport?: () => boolean
}

interface LaunchGameResult {
  pid: number
  launch_id?: string
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
  profile?: LaunchProfileOptions,
): Promise<{ pid: number; sessionId: number | null; trackingOwnedElsewhere?: boolean }> {
  if (!isTauriRuntime()) {
    throw new Error('Launch is only available in the desktop app')
  }
  if (profile && !profile.current()) throw new Error('Account profile changed before launch')

  const record = await getInstallRecord(gameUuid)
  if (!record) {
    throw new Error(`No local install found for ${gameUuid}`)
  }
  if (profile && !profile.current()) throw new Error('Account profile changed before launch')

  const launchResult = await invoke<LaunchGameResult>('launch_game', {
    gameUuid,
    exePath: record.exePath ?? null,
    extractPath: record.extractPath,
    ...(profile ? { profileBinding: profile.profileBinding } : {}),
  })

  if (launchResult.resolved_exe_path) {
    try {
      await persistResolvedExePath(gameUuid, record, launchResult.resolved_exe_path)
    } catch {
      // The process already exists; a registry write must not report launch failure.
    }
  }

  let sessionId: number | null = null
  const launchId = launchResult.launch_id
  const canTrack = hasNativeLaunchIdentity(launchResult.pid, launchId)
  if (profile) {
    if (
      !canTrack ||
      !profile.profileBinding ||
      !profile.current() ||
      profile.canReport?.() === false
    ) {
      return { pid: launchResult.pid, sessionId: null }
    }
    const reportingCurrent = profile.canReport
      ? () => profile.current() && profile.canReport!()
      : profile.current
    const result = await launchRecovery.begin(
      api,
      profile.profileBinding,
      gameUuid,
      reportingCurrent,
      true,
    )
    if (result.state !== 'unsupported') {
      return {
        pid: launchResult.pid,
        sessionId: result.sessionId,
        ...(result.state === 'owned_elsewhere' ? { trackingOwnedElsewhere: true } : {}),
      }
    }
    // macOS retains current-session direct-child reporting until its native
    // family/restart mechanism is independently qualified.
  }
  if (canTrack) {
    try {
      const session = await api.playtime.startSession({
        game_uuid: gameUuid,
        client: 'desktop',
      })
      if (typeof session.id === 'number' && Number.isInteger(session.id) && session.id > 0) {
        sessionId = session.id
      }
    } catch {
      // Offline play remains a successful local launch, without invented playtime.
    }
  }

  const existing = activeWatchers.get(gameUuid)
  if (existing) {
    await existing.stop()
    activeWatchers.delete(gameUuid)
  }

  if (canTrack) {
    activeWatchers.set(gameUuid, watchPlaySession(api, launchResult.pid, sessionId, { launchId }))
  }

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
  await launchRecovery.stopGame(gameUuid)
  const watcher = activeWatchers.get(gameUuid)
  if (!watcher) {
    return
  }
  await watcher.stop()
  activeWatchers.delete(gameUuid)
}

/** Retire profile tracking without killing any locally running game. */
export function stopAllLaunchWatchers(): void {
  launchRecovery.stopAll()
  const watchers = [...activeWatchers.values()]
  activeWatchers.clear()
  for (const watcher of watchers) {
    // stop clears its timer synchronously; its final server report is best-effort.
    void watcher.stop().catch(() => undefined)
  }
}
