import { describe, expect, it } from 'vitest'
import { createRequester, formatBearerAuthorization, OneirodexApiError } from './client.js'

describe('formatBearerAuthorization', () => {
  it('prefixes gt_ token with Bearer', () => {
    expect(formatBearerAuthorization('gt_ab12_secret')).toBe('Bearer gt_ab12_secret')
  })

  it('normalizes existing Bearer prefix', () => {
    expect(formatBearerAuthorization('bearer gt_ab12_secret')).toBe('Bearer gt_ab12_secret')
  })
})

describe('OneirodexApiError', () => {
  it('surfaces error_code and status from a full error envelope', () => {
    const err = new OneirodexApiError(403, {
      ok: false,
      error: 'Admin required',
      error_code: 'forbidden',
      message: 'Admin required',
      detail: { field: 'role' },
    })
    expect(err.status).toBe(403)
    expect(err.error_code).toBe('forbidden')
    expect(err.message).toBe('Admin required')
  })

  it('keeps message as the human string for legacy { error } bodies', () => {
    const err = new OneirodexApiError(401, { error: 'unauthorized' })
    expect(err.message).toBe('unauthorized')
    expect(err.error_code).toBeNull()
  })

  it('falls back to HTTP <status> when the body carries no error string', () => {
    const err = new OneirodexApiError(502, 'upstream exploded')
    expect(err.message).toBe('HTTP 502')
    expect(err.error_code).toBeNull()
    expect(err.body).toBe('upstream exploded')
  })

  it('treats an explicit null error_code as null, not a crash', () => {
    const err = new OneirodexApiError(502, { ok: false, error: 'Bad upstream', error_code: null })
    expect(err.error_code).toBeNull()
    expect(err.message).toBe('Bad upstream')
  })
})

describe('createRequester error parsing', () => {
  const jsonResponse = (status: number, body: unknown): Response =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    })

  it('throws OneirodexApiError carrying error_code + status from the envelope', async () => {
    const request = createRequester({
      baseUrl: 'https://host.example',
      getToken: () => null,
      fetchImpl: async () =>
        jsonResponse(409, { ok: false, error: 'Already exists', error_code: 'conflict' }),
    })

    await expect(request('/api/thing')).rejects.toMatchObject({
      name: 'OneirodexApiError',
      status: 409,
      error_code: 'conflict',
      message: 'Already exists',
    })
  })

  it('passes a success envelope through as T', async () => {
    interface Payload {
      ok: true
      error: null
      error_code: null
      collections: string[]
    }
    const request = createRequester({
      baseUrl: 'https://host.example',
      getToken: () => null,
      fetchImpl: async () =>
        jsonResponse(200, { ok: true, error: null, error_code: null, collections: ['a', 'b'] }),
    })

    const body = await request<Payload>('/api/collections')
    expect(body.collections).toEqual(['a', 'b'])
    expect(body.ok).toBe(true)
  })

  it('refuses redirects for bearer API requests', async () => {
    let requestInit: RequestInit | undefined
    const request = createRequester({
      baseUrl: 'https://host.example',
      getToken: () => 'gt_secret',
      fetchImpl: async (_input, init) => {
        requestInit = init
        return jsonResponse(200, { ok: true, error: null, error_code: null })
      },
    })

    await request('/api/thing')

    expect(requestInit?.redirect).toBe('error')
  })
})
