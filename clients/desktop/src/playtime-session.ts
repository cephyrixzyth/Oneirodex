import type { OneirodexClient } from './api.js'
import { isProcessRunning as defaultIsProcessRunning } from './process-status.js'

export interface PlaySessionWatcher {
  stop(): Promise<void>
}

export interface WatchPlaySessionOptions {
  pollIntervalMs?: number
  isProcessRunning?: (pid: number) => Promise<boolean>
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

  const stop = async (): Promise<void> => {
    if (stopped) {
      return
    }
    stopped = true
    if (timer !== undefined) {
      clearIntervalImpl(timer)
      timer = undefined
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
      const running = await isProcessRunning(pid)
      if (!running) {
        await stop()
        return
      }
      if (sessionId !== null) await api.playtime.heartbeatSession(sessionId)
    } catch {
      await stop()
    }
  }

  timer = setIntervalImpl(() => {
    void tick()
  }, pollIntervalMs)

  return { stop }
}
