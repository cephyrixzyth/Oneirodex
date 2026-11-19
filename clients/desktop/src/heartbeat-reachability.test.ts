import { afterEach, describe, expect, it, vi } from 'vitest'

import { createAuthStore } from './auth.js'
import { startClientHeartbeat } from './heartbeat.js'

describe('startClientHeartbeat reachability', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('calls onUnreachable after consecutive failures, then onReachable on recovery', async () => {
    vi.useFakeTimers()
    const auth = createAuthStore()
    auth.setBaseUrl('https://example.com')
    auth.setToken('gt_prefix_secret')

    const onReachable = vi.fn()
    const onUnreachable = vi.fn()
    let fail = true
    // Shaped like a real Response: the heartbeat goes through
    // @oneirodex/api-client, which reads content-type and text() on failures.
    const fetchImpl = vi.fn().mockImplementation(async () => {
      if (fail) {
        return {
          ok: false,
          status: 503,
          headers: new Headers(),
          text: async () => '',
          json: async () => ({}),
        }
      }
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => '{"commands":[]}',
        json: async () => ({ commands: [] }),
      }
    })

    const scheduler = startClientHeartbeat(auth, {
      intervalMs: 1000,
      unreachableAfterFailures: 2,
      fetchImpl: fetchImpl as typeof fetch,
      onReachable,
      onUnreachable,
    })

    await vi.advanceTimersByTimeAsync(0)
    await Promise.resolve()
    expect(onUnreachable).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1000)
    await Promise.resolve()
    expect(onUnreachable).toHaveBeenCalledTimes(1)

    fail = false
    await vi.advanceTimersByTimeAsync(1000)
    await Promise.resolve()
    expect(onReachable).toHaveBeenCalled()

    scheduler.stop()
  })
  it('acknowledges a redelivered lease after restart without executing twice', async () => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) || null,
      setItem: (key: string, value: string) => storage.set(key, value),
    })
    const auth = createAuthStore({ baseUrl: 'https://example.com', token: 'gt_prefix_secret' })
    const onCommands = vi.fn(async () => 'ok' as const)
    let first = true
    const leases: string[] = []
    const fetchImpl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body))
      if (String(url).endsWith('/heartbeat')) {
        expect(body.command_protocol).toBe(2)
        return Response.json({
          commands: [
            {
              id: 'operation-a',
              game_uuid: 'g',
              action: 'download',
              lease_id: first ? 'lease-one' : 'lease-two',
            },
          ],
        })
      }
      expect(body.device_id).toBe('den')
      leases.push(body.lease_id)
      return first ? Response.json({}, { status: 503 }) : Response.json({ removed: 1 })
    })
    const opts = { deviceId: 'den', intervalMs: 60000, onCommands, fetchImpl }
    let scheduler = startClientHeartbeat(auth, opts)
    try {
      await vi.waitFor(() => expect(leases).toEqual(['lease-one']))
      scheduler.stop()
      expect([...storage.keys()].join('')).not.toContain('gt_prefix_secret')
      first = false
      scheduler = startClientHeartbeat(auth, opts)
      await vi.waitFor(() => expect(leases).toEqual(['lease-one', 'lease-two']))
      expect(onCommands).toHaveBeenCalledTimes(1)
    } finally {
      scheduler.stop()
      vi.unstubAllGlobals()
    }
  })
})
