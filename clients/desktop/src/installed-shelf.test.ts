import { afterEach, describe, expect, it, vi } from 'vitest'
import { createAuthStore } from './auth.js'
import { createDesktopApi } from './api.js'
import { readInstalledShelf } from './installed-shelf.js'

const record = { archivePath: 'fixture.zip', extractPath: 'fixture', exePath: 'fixture.exe' }
afterEach(() => vi.unstubAllGlobals())
describe('verified installed inventory', () => {
  it('rejects malformed preview metadata rather than silently dropping an installed title from cache', async () => {
    const api = createDesktopApi(
      createAuthStore({ baseUrl: 'https://review.example', token: 'fixture' }),
      async () => {
        throw new Error('Preview ID should not need another read')
      },
    )
    await expect(
      readInstalledShelf(
        api,
        { game: record },
        () => true,
        [{ uuid: 'game', name: 'x'.repeat(301) }],
        () => true,
      ),
    ).rejects.toThrow()
  })
  it('reads all thirteen local installed titles with at most four requests in flight', async () => {
    const installs = Object.fromEntries(
      Array.from({ length: 13 }, (_, index) => [`game-${index}`, record]),
    )
    let active = 0
    let peak = 0
    const paths: string[] = []
    const api = createDesktopApi(
      createAuthStore({ baseUrl: 'https://review.example', token: 'fixture' }),
      async (url) => {
        active += 1
        peak = Math.max(peak, active)
        paths.push(String(url))
        await new Promise<void>((resolve) => setTimeout(resolve, 1))
        active -= 1
        const uuid = new URL(String(url)).pathname.split('/')[3]
        return Response.json({ uuid, name: `Title ${uuid}`, private_notes: 'never cached' })
      },
    )
    const games = await readInstalledShelf(
      api,
      installs,
      () => true,
      [],
      () => true,
    )
    expect(games).toHaveLength(13)
    expect(games[12]).toEqual({ uuid: 'game-12', name: 'Title game-12' })
    expect(paths).toHaveLength(13)
    expect(peak).toBeLessThanOrEqual(4)
  })

  it('omits denied, missing, pending-uninstall and nonlaunchable local records', async () => {
    const requested: string[] = []
    const api = createDesktopApi(
      createAuthStore({ baseUrl: 'https://review.example', token: 'fixture' }),
      async (url) => {
        const uuid = new URL(String(url)).pathname.split('/')[3]
        requested.push(uuid)
        return uuid === 'denied'
          ? Response.json({ error: 'Forbidden' }, { status: 403 })
          : new Response(null, { status: 404 })
      },
    )
    expect(
      await readInstalledShelf(
        api,
        {
          denied: record,
          missing: record,
          pending: { ...record, pendingUninstall: true },
          downloaded: record,
        },
        (id) => id !== 'downloaded',
        [],
        () => true,
      ),
    ).toEqual([])
    expect(requested.sort()).toEqual(['denied', 'missing'])
  })

  it.each(['transport', 'service', 'wrong-uuid'])(
    'fails the entire refresh on %s rather than returning a partial inventory',
    async (kind) => {
      const api = createDesktopApi(
        createAuthStore({ baseUrl: 'https://review.example', token: 'fixture' }),
        async () => {
          if (kind === 'transport') throw new TypeError('Failed to fetch')
          if (kind === 'service') return Response.json({ error: 'Unavailable' }, { status: 503 })
          return Response.json({ uuid: 'other-account-game', name: 'Do not display' })
        },
      )
      await expect(
        readInstalledShelf(
          api,
          { game: record },
          () => true,
          [],
          () => true,
        ),
      ).rejects.toThrow()
    },
  )

  it('refuses an over-capacity cache before requesting or publishing a partial success', async () => {
    const requests: string[] = []
    const api = createDesktopApi(
      createAuthStore({ baseUrl: 'https://review.example', token: 'fixture' }),
      async (url) => {
        requests.push(String(url))
        return Response.json({})
      },
    )
    const installs = Object.fromEntries(
      Array.from({ length: 5001 }, (_, index) => [`game-${index}`, record]),
    )
    await expect(
      readInstalledShelf(
        api,
        installs,
        () => true,
        [],
        () => true,
      ),
    ).rejects.toThrow(/5,000|5000/)
    expect(requests).toEqual([])
  })

  it('does not continue scheduling metadata reads after the connection changes', async () => {
    let current = true
    const requests: string[] = []
    const api = createDesktopApi(
      createAuthStore({ baseUrl: 'https://review.example', token: 'fixture' }),
      async (url) => {
        requests.push(String(url))
        current = false
        return Response.json({ uuid: 'game-0', name: 'Old account title' })
      },
    )
    const installs = Object.fromEntries(
      Array.from({ length: 20 }, (_, index) => [`game-${index}`, record]),
    )
    await expect(
      readInstalledShelf(
        api,
        installs,
        () => true,
        [],
        () => current,
      ),
    ).rejects.toMatchObject({ name: 'AbortError' })
    expect(requests.length).toBeLessThanOrEqual(4)
  })
})
