import { afterEach, describe, expect, it, vi } from 'vitest'
import { createAuthStore } from './auth.js'
import { createDesktopApi } from './api.js'
import { validateConnection } from './connect.js'
import { createServer } from 'node:http'
import { once } from 'node:events'

afterEach(() => vi.unstubAllGlobals())
const auth = () => createAuthStore({ baseUrl: 'https://a.example', token: 'gt_abcdef01_fixtureA' })
describe('desktop control-plane transport', () => {
  it('refuses a real HTTP redirect without forwarding a bearer request to its destination', async () => {
    let sinkRequests = 0
    let originBearer: string | undefined
    const sink = createServer((_req, res) => {
      sinkRequests += 1
      res.end('unexpected')
    })
    const origin = createServer((req, res) => {
      originBearer = req.headers.authorization
      const address = sink.address()
      if (!address || typeof address === 'string') throw new Error('Missing sink port')
      res.writeHead(302, { Location: `http://127.0.0.1:${address.port}/sink` })
      res.end()
    })
    try {
      sink.listen(0, '127.0.0.1')
      await once(sink, 'listening')
      origin.listen(0, '127.0.0.1')
      await once(origin, 'listening')
      const address = origin.address()
      if (!address || typeof address === 'string') throw new Error('Missing origin port')
      const api = createDesktopApi(
        createAuthStore({
          baseUrl: `http://127.0.0.1:${address.port}`,
          token: 'gt_abcdef01_synthetic',
        }),
      )
      expect(await validateConnection(api)).toMatchObject({ ok: false, cause: 'redirect_refused' })
      expect(originBearer).toBe('Bearer gt_abcdef01_synthetic')
      expect(sinkRequests).toBe(0)
    } finally {
      origin.closeAllConnections()
      sink.closeAllConnections()
      await Promise.all([
        new Promise<void>((done) => origin.close(() => done())),
        new Promise<void>((done) => sink.close(() => done())),
      ])
    }
  })
  it.each(['actual', 'opaque', 'followed'])(
    'refuses %s redirects distinctly from outages',
    async (kind) => {
      const response =
        kind === 'actual'
          ? new Response(null, { status: 302, headers: { Location: 'https://sink.example/login' } })
          : Response.json([])
      if (kind === 'opaque') Object.defineProperty(response, 'type', { value: 'opaqueredirect' })
      if (kind === 'followed') Object.defineProperty(response, 'redirected', { value: true })
      const requests: {
        url: string
        redirect: RequestRedirect | undefined
        bearer: string | null
      }[] = []
      vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
        requests.push({
          url: String(url),
          redirect: init.redirect,
          bearer: new Headers(init.headers).get('Authorization'),
        })
        return response
      })
      const result = await validateConnection(createDesktopApi(auth()))
      expect(result).toMatchObject({ ok: false, cause: 'redirect_refused' })
      expect(requests).toEqual([
        {
          url: 'https://a.example/api/collections',
          redirect: 'manual',
          bearer: 'Bearer gt_abcdef01_fixtureA',
        },
      ])
    },
  )
  it('does not mislabel programming TypeErrors as a network outage', async () => {
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('Cannot read properties of undefined')
    })
    expect(await validateConnection(createDesktopApi(auth()))).toMatchObject({
      ok: false,
      cause: 'unknown',
    })
  })
  it('still classifies real fetch failures as network errors', async () => {
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('Failed to fetch')
    })
    expect(await validateConnection(createDesktopApi(auth()))).toMatchObject({
      ok: false,
      cause: 'network',
    })
  })
  it('rejects HTML success as a protocol failure', async () => {
    vi.stubGlobal(
      'fetch',
      async () => new Response('<html>login</html>', { headers: { 'content-type': 'text/html' } }),
    )
    expect(await validateConnection(createDesktopApi(auth()))).toMatchObject({
      ok: false,
      cause: 'protocol',
    })
  })
})
