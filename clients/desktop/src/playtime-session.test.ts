import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createOneirodexClient } from '@oneirodex/api-client'

import { watchPlaySession } from './playtime-session.js'

describe('playtime session watcher', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('watches an offline process without sending a nonexistent remote session', async () => {
    const fetchImpl = vi.fn()
    const api = createOneirodexClient({
      baseUrl: 'https://example.com',
      getToken: () => 'test',
      fetchImpl,
    })
    const isProcessRunning = vi.fn().mockResolvedValueOnce(true).mockResolvedValue(false)
    const watcher = watchPlaySession(api, 42, null, { pollIntervalMs: 1000, isProcessRunning })
    await vi.advanceTimersByTimeAsync(3000)
    expect(isProcessRunning).toHaveBeenCalledTimes(2)
    expect(fetchImpl).not.toHaveBeenCalled()
    await watcher.stop()
    expect(vi.getTimerCount()).toBe(0)
    vi.useRealTimers()
  })

  it('heartbeats while the process is running and stops when it exits', async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/heartbeat') && init?.method === 'POST') {
        return new Response(JSON.stringify({ id: 7, status: 'active' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.endsWith('/stop') && init?.method === 'POST') {
        return new Response(JSON.stringify({ id: 7, status: 'ended' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response('not found', { status: 404 })
    })

    const api = createOneirodexClient({
      baseUrl: 'https://example.com',
      getToken: () => 'gt_abcd_secret',
      fetchImpl,
    })

    let running = true
    const watcher = watchPlaySession(api, 4242, 7, {
      pollIntervalMs: 1000,
      isProcessRunning: async () => running,
    })

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://example.com/api/playtime/sessions/7/heartbeat',
      expect.objectContaining({ method: 'POST' }),
    )

    running = false
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://example.com/api/playtime/sessions/7/stop',
      expect.objectContaining({ method: 'POST' }),
    )

    await watcher.stop()
    vi.useRealTimers()
  })
})
