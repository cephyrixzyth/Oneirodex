import type { OneirodexClient } from './api.js'
import { isProcessRunning as defaultIsProcessRunning } from './process-status.js'

export interface PlaySessionWatcher {
  stop(): Promise<void>
}

export interface WatchPlaySessionOptions {
  onStopped?: (reason: 'stopped' | 'ended' | 'unavailable') => void
  launchId?: string
  pollIntervalMs?: number
  isProcessRunning?: (pid: number, launchId?: string) => Promise<boolean>
  setIntervalImpl?: typeof setInterval
  clearIntervalImpl?: typeof clearInterval
}

const DEFAULT_POLL_INTERVAL_MS = 30_000

export function watchPlaySession(
  api: OneirodexClient,
  pid: number,
  sessionId: number | null,
  options: WatchPlaySessionOptions = {},
): PlaySessionWatcher {
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS
  const setIntervalImpl = options.setIntervalImpl ?? setInterval
  const clearIntervalImpl = options.clearIntervalImpl ?? clearInterval
  let stopped = false
  let timer: ReturnType<typeof setInterval> | undefined

  const isProcessRunning = options.isProcessRunning ?? defaultIsProcessRunning

  const stop = async (reason: 'stopped' | 'ended' | 'unavailable' = 'stopped'): Promise<void> => {
    if (stopped) {
      return
    }
    stopped = true
    if (timer !== undefined) {
      clearIntervalImpl(timer)
      timer = undefined
    }
    try {
      options.onStopped?.(reason)
    } catch {
      // Local cleanup must not prevent the best-effort server stop.
    }
    try {
      if (sessionId !== null) await api.playtime.stopSession(sessionId)
    } catch {
      // Best-effort stop when the game exits or polling fails hard.
    }
  }

  const tick = async (): Promise<void> => {
    if (stopped) {
      return
    }

    try {
      const running = await isProcessRunning(pid, options.launchId)
      if (stopped) return
      if (!running) {
        await stop('ended')
        return
      }
      if (sessionId !== null) await api.playtime.heartbeatSession(sessionId)
    } catch {
      await stop('unavailable')
    }
  }

  timer = setIntervalImpl(() => {
    void tick()
  }, pollIntervalMs)

  return { stop }
}
