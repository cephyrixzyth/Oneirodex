import { afterEach, describe, expect, it, vi } from 'vitest'
import { createAuthStore } from './auth.js'
import { startClientHeartbeat } from './heartbeat.js'

const reply = () =>
  Response.json({ commands: [{ id: 'command-a', game_uuid: 'game-a', action: 'install' }] })
const authForA = () =>
  createAuthStore({ baseUrl: 'https://a.example', token: 'gt_abcdef01_fixtureA' })
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('heartbeat identity and access boundaries', () => {
  it('keeps HTTP denial authoritative when its body contains a network-error phrase', async () => {
    vi.useFakeTimers()
    const onFailure = vi.fn()
    const onUnreachable = vi.fn()
    const scheduler = startClientHeartbeat(authForA(), {
      fetchImpl: async () => Response.json({ error: 'Failed to fetch' }, { status: 403 }),
      onFailure,
      onUnreachable,
      unreachableAfterFailures: 1,
    })
    await vi.advanceTimersByTimeAsync(0)
    scheduler.stop()
    expect(onFailure).toHaveBeenCalledTimes(1)
    expect(onUnreachable).not.toHaveBeenCalled()
  })
  it.each([401, 403])('reports HTTP %s as access failure, never an outage', async (status) => {
    vi.useFakeTimers()
    const onFailure = vi.fn()
    const onUnreachable = vi.fn()
    const scheduler = startClientHeartbeat(authForA(), {
      fetchImpl: async () => Response.json({ error: 'denied' }, { status }),
      onFailure,
      onUnreachable,
      unreachableAfterFailures: 1,
    })
    await vi.advanceTimersByTimeAsync(0)
    scheduler.stop()
    expect(onFailure).toHaveBeenCalledTimes(1)
    expect(onUnreachable).not.toHaveBeenCalled()
  })

  it.each(['stop', 'token', 'server', 'roundtrip'])(
    'discards a late heartbeat after %s',
    async (change) => {
      vi.useFakeTimers()
      const auth = authForA()
      const pending = deferred<Response>()
      const onReachable = vi.fn()
      const onCommands = vi.fn()
      const requests: string[] = []
      const scheduler = startClientHeartbeat(auth, {
        fetchImpl: async (url) => {
          requests.push(String(url))
          return pending.promise
        },
        onReachable,
        onCommands,
      })
      await vi.advanceTimersByTimeAsync(0)
      if (change === 'stop') scheduler.stop()
      if (change === 'token') auth.setToken('gt_abcdef02_fixtureB')
      if (change === 'server') auth.setBaseUrl('https://b.example')
      if (change === 'roundtrip') {
        auth.setToken('gt_abcdef02_fixtureB')
        auth.setToken('gt_abcdef01_fixtureA')
      }
      pending.resolve(reply())
      await vi.advanceTimersByTimeAsync(0)
      scheduler.stop()
      expect(onReachable).not.toHaveBeenCalled()
      expect(onCommands).not.toHaveBeenCalled()
      expect(requests).toEqual(['https://a.example/api/client/heartbeat'])
    },
  )

  it('does not acknowledge an old command after its handler crosses an identity change', async () => {
    vi.useFakeTimers()
    const auth = authForA()
    const handled = deferred<'ok'>()
    const requests: { url: string; bearer: string | null }[] = []
    const scheduler = startClientHeartbeat(auth, {
      fetchImpl: async (url, init) => {
        requests.push({ url: String(url), bearer: new Headers(init?.headers).get('Authorization') })
        return reply()
      },
      onCommands: () => handled.promise,
    })
    await vi.advanceTimersByTimeAsync(0)
    auth.setBaseUrl('https://b.example')
    auth.setToken('gt_abcdef02_fixtureB')
    handled.resolve('ok')
    await vi.advanceTimersByTimeAsync(0)
    scheduler.stop()
    expect(requests).toEqual([
      { url: 'https://a.example/api/client/heartbeat', bearer: 'Bearer gt_abcdef01_fixtureA' },
    ])
  })
})
