import { describe, expect, it, vi } from 'vitest'
import { createBrowserRequester } from './transport-browser.js'
import { createRequester, OneirodexApiError } from './client.js'

interface Call {
  url: string
  init: RequestInit
}

function recordingFetch(status: number, body: unknown) {
  const calls: Call[] = []
  const fetchImpl = (async (url: string | URL, init: RequestInit = {}) => {
    calls.push({ url: String(url), init })
    return new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: status === 204 ? undefined : { 'content-type': 'application/json' },
    })
  }) as unknown as typeof fetch
  return { calls, fetchImpl }
}

describe('createBrowserRequester', () => {
  it('sends credentials: include and X-CSRFToken on mutations', async () => {
    const { calls, fetchImpl } = recordingFetch(200, { ok: true, error: null, error_code: null })
    const request = createBrowserRequester({
      baseUrl: 'https://app.example',
      fetchImpl,
      csrfToken: () => 'csrf-abc',
    })

    await request('/api/collections', { method: 'POST', body: '{}' })

    const { init } = calls[0]
    expect(init.credentials).toBe('include')
    expect(new Headers(init.headers).get('X-CSRFToken')).toBe('csrf-abc')
  })

  it('omits X-CSRFToken on GET but still includes credentials', async () => {
    const { calls, fetchImpl } = recordingFetch(200, { ok: true, error: null, error_code: null })
    const request = createBrowserRequester({
      baseUrl: 'https://app.example',
      fetchImpl,
      csrfToken: () => 'csrf-abc',
    })

    await request('/api/collections')

    const { init } = calls[0]
    expect(init.credentials).toBe('include')
    expect(new Headers(init.headers).get('X-CSRFToken')).toBeNull()
  })

  it('fires onUnauthorized once on 401, then throws OneirodexApiError', async () => {
    const { fetchImpl } = recordingFetch(401, {
      ok: false,
      error: 'Session expired',
      error_code: 'unauthorized',
    })
    const onUnauthorized = vi.fn()
    const request = createBrowserRequester({
      baseUrl: 'https://app.example',
      fetchImpl,
      onUnauthorized,
    })

    await expect(request('/api/tokens')).rejects.toMatchObject({
      name: 'OneirodexApiError',
      status: 401,
      error_code: 'unauthorized',
    })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('treats a followed same-origin login redirect as unauthorized', async () => {
    const response = {
      ok: true,
      status: 200,
      redirected: true,
      url: 'https://app.example/login?next=%2Fapi%2Ftokens',
      headers: new Headers({ 'content-type': 'text/html' }),
    } as Response
    const onUnauthorized = vi.fn()
    const request = createBrowserRequester({
      baseUrl: 'https://app.example',
      fetchImpl: vi.fn(async () => response) as unknown as typeof fetch,
      onUnauthorized,
    })

    await expect(request('/api/tokens')).rejects.toMatchObject({
      name: 'OneirodexApiError',
      status: 401,
      error_code: 'unauthorized',
    })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('does not classify a cross-origin login page as the app login redirect', async () => {
    const response = {
      ok: true,
      status: 200,
      redirected: true,
      url: 'https://identity.example/login',
      headers: new Headers({ 'content-type': 'text/html' }),
    } as Response
    const onUnauthorized = vi.fn()
    const request = createBrowserRequester({
      baseUrl: 'https://app.example',
      fetchImpl: vi.fn(async () => response) as unknown as typeof fetch,
      onUnauthorized,
    })

    await expect(request('/api/tokens')).resolves.toBeUndefined()
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('does not fire onUnauthorized on a 403', async () => {
    const { fetchImpl } = recordingFetch(403, {
      ok: false,
      error: 'Forbidden',
      error_code: 'forbidden',
    })
    const onUnauthorized = vi.fn()
    const request = createBrowserRequester({
      baseUrl: 'https://app.example',
      fetchImpl,
      onUnauthorized,
    })

    await expect(request('/api/tokens')).rejects.toBeInstanceOf(OneirodexApiError)
    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})

describe('Bearer transport is unchanged', () => {
  it('sets Authorization from getToken and no credentials/CSRF', async () => {
    const calls: Call[] = []
    const fetchImpl = (async (url: string | URL, init: RequestInit = {}) => {
      calls.push({ url: String(url), init })
      return new Response(JSON.stringify({ ok: true, error: null, error_code: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }) as unknown as typeof fetch

    const request = createRequester({
      baseUrl: 'https://host.example',
      getToken: () => 'gt_ab12_secret',
      fetchImpl,
    })

    await request('/api/tokens', { method: 'POST', body: '{}' })

    const { init } = calls[0]
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer gt_ab12_secret')
    expect(new Headers(init.headers).get('X-CSRFToken')).toBeNull()
    expect(init.credentials).toBeUndefined()
  })
})
