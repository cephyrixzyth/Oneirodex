import { afterEach, expect, it, vi } from 'vitest'
import { createOneirodexClient } from '@oneirodex/api-client'
import { watchPlaySession } from './playtime-session.js'
afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})
it('never sends a late playtime heartbeat after tracking stops during a native process check', async () => {
  vi.useFakeTimers()
  let finish!: (running: boolean) => void
  const pending = new Promise<boolean>((resolve) => {
    finish = resolve
  })
  const paths: string[] = []
  const api = createOneirodexClient({
    baseUrl: 'https://a.example',
    getToken: () => 'fixture',
    fetchImpl: async (url) => {
      paths.push(new URL(String(url)).pathname)
      return Response.json({})
    },
  })
  const watcher = watchPlaySession(api, 42, 7, {
    pollIntervalMs: 1000,
    isProcessRunning: () => pending,
  })
  await vi.advanceTimersByTimeAsync(1000)
  await watcher.stop()
  finish(true)
  await vi.advanceTimersByTimeAsync(0)
  expect(paths).toEqual(['/api/playtime/sessions/7/stop'])
})
