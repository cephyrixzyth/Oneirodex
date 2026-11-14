import { afterEach, expect, test, vi } from 'vitest'
import { fetchVrCatalog, fetchVrGame } from './vr'

afterEach(() => vi.unstubAllGlobals())

function privateRequests() {
  const fetch = vi.fn(
    async (_url: RequestInfo | URL) =>
      new Response(JSON.stringify({ games: [] }), {
        headers: { 'Content-Type': 'application/json' },
      }),
  )
  vi.stubGlobal('fetch', fetch)
  vi.stubGlobal('navigator', {
    serviceWorker: { controller: { scriptURL: `${location.origin}/vr/sw.js` } },
  })
  return fetch
}

test('catalog and detail both reject uncoordinated legacy control', async () => {
  const fetch = privateRequests()
  await expect(fetchVrCatalog()).rejects.toThrow('Reconnect and reload')
  await expect(fetchVrGame('fixture')).rejects.toThrow('Reconnect and reload')
  expect(fetch).not.toHaveBeenCalled()
})

test('acknowledged retirement control permits normal private reads', async () => {
  const fetch = privateRequests()
  vi.stubGlobal('odPwaPrivacyReady', Promise.resolve(true))
  await fetchVrCatalog()
  await fetchVrGame('fixture')
  expect(fetch.mock.calls.map(([url]) => String(url))).toEqual([
    '/api/vr/catalog?page=1&per_page=48',
    '/api/vr/games/fixture',
  ])
})

test('cancelled catalog and detail do not start after privacy readiness', async () => {
  const fetch = privateRequests()
  let resolve!: (ready: boolean) => void
  vi.stubGlobal(
    'odPwaPrivacyReady',
    new Promise<boolean>((done) => {
      resolve = done
    }),
  )
  const controller = new AbortController()
  const catalog = expect(fetchVrCatalog({ signal: controller.signal })).rejects.toMatchObject({
    name: 'AbortError',
  })
  const detail = expect(
    fetchVrGame('fixture', { signal: controller.signal }),
  ).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  resolve(true)
  await Promise.all([catalog, detail])
  expect(fetch).not.toHaveBeenCalled()
})

test('browsing without service worker support remains available', async () => {
  const fetch = privateRequests()
  vi.stubGlobal('navigator', {})
  await fetchVrCatalog()
  expect(fetch).toHaveBeenCalledTimes(1)
})
