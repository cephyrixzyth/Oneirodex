import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from '@oneirodex/ui'
import { loadMoonfallProgress, saveMoonfallProgress, resetMoonfallProgress } from './progress'
import savedRun from '../../../../../tests/fixtures/moonfall-save-v1.json'

const body = (revision = 1, state: unknown = savedRun) => ({
  game_id: 'moonfall-pinball',
  revision,
  state,
  updated_at: null,
  ok: true,
})
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
beforeEach(() => {
  vi.stubGlobal('odPwaPrivacyReady', Promise.resolve(true))
  setCsrfToken('synthetic-room-csrf')
})
afterEach(() => {
  vi.unstubAllGlobals()
  setCsrfToken('')
})

describe('member-scoped Moonfall progress transport', () => {
  it('uses a private same-origin read and validates the returned save', async () => {
    const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => response(body()))
    vi.stubGlobal('fetch', fetch)
    const result = await loadMoonfallProgress()
    expect(result.state).toEqual(savedRun)
    expect(fetch.mock.calls[0][0]).toBe('/api/room-games/moonfall-pinball/progress')
    expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: 'include', cache: 'no-store' })
  })

  it('sends mutations with the shared CSRF header and explicit revision, never a client owner', async () => {
    const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => response(body(8)))
    vi.stubGlobal('fetch', fetch)
    await saveMoonfallProgress(7, savedRun)
    const init = fetch.mock.calls[0][1]!
    expect(init.method).toBe('PUT')
    expect(new Headers(init.headers).get('X-CSRFToken')).toBe('synthetic-room-csrf')
    expect(JSON.parse(init.body as string)).toEqual({ revision: 7, state: savedRun })
  })

  it('resets only the explicit revision and returns its empty tombstone', async () => {
    const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      response(body(8, null)),
    )
    vi.stubGlobal('fetch', fetch)
    expect((await resetMoonfallProgress(7)).state).toBeNull()
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: 'DELETE',
      body: JSON.stringify({ revision: 7 }),
    })
  })

  it('preserves conflict and denial machine fields for the UI', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response({ error: 'Saved game changed.', error_code: 'conflict' }, 409)),
    )
    await expect(saveMoonfallProgress(7, savedRun)).rejects.toMatchObject({
      status: 409,
      error_code: 'conflict',
    })
  })

  it('rejects malformed and unsupported saves instead of treating them as no saved game', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response(body(1, { ...savedRun, version: 999 }))),
    )
    await expect(loadMoonfallProgress()).rejects.toThrow()
  })

  it('rejects invalid local snapshots before starting a request', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(saveMoonfallProgress(0, { ...savedRun, score: NaN })).rejects.toThrow()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('blocks reads and writes behind an unretired legacy VR worker', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    vi.stubGlobal('odPwaPrivacyReady', Promise.resolve(false))
    vi.stubGlobal('navigator', {
      serviceWorker: { controller: { scriptURL: location.origin + '/vr/sw.js' } },
    })
    await expect(loadMoonfallProgress()).rejects.toThrow('Reconnect and reload')
    await expect(saveMoonfallProgress(0, savedRun)).rejects.toThrow('Reconnect and reload')
    await expect(resetMoonfallProgress(0)).rejects.toThrow('Reconnect and reload')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('does not fetch after cancellation while waiting for privacy readiness', async () => {
    let ready!: (value: boolean) => void
    vi.stubGlobal(
      'odPwaPrivacyReady',
      new Promise<boolean>((resolve) => {
        ready = resolve
      }),
    )
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const controller = new AbortController()
    const result = expect(loadMoonfallProgress(controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    })
    controller.abort()
    ready(true)
    await result
    expect(fetch).not.toHaveBeenCalled()
  })
})
