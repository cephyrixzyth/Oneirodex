import { afterEach, describe, expect, test, vi } from 'vitest'

import { registerAccount, requestPasswordReset, resetPassword, signIn } from './authApi.js'

describe('signIn', () => {
  afterEach(() => vi.unstubAllGlobals())

  test('posts same-origin JSON with CSRF and preserves an encoded next path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ next_url: '/library' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    document.head.innerHTML = '<meta name="csrf-token" content="csrf-value">'

    await expect(
      signIn({ username: 'alice', password: 'pass word' }, { next: '/library?q=zelda' }),
    ).resolves.toEqual({ next_url: '/library' })

    expect(fetchMock).toHaveBeenCalledWith('/api/auth/login?next=%2Flibrary%3Fq%3Dzelda', {
      method: 'POST',
      credentials: 'same-origin',
      signal: undefined,
      headers: { 'X-CSRFToken': 'csrf-value', 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'alice', password: 'pass word' }),
    })
  })

  test('registers with an encoded invite token and returns a generic acknowledgement', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        requested: true,
        message: 'If eligible, check your email.',
        next_url: '/login',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    document.head.innerHTML = '<meta name="csrf-token" content="csrf-value">'
    const body = { username: 'guest', email: 'guest@example.com', password: 'long-enough' }

    await expect(registerAccount(body, { inviteToken: 'invite / secret' })).resolves.toEqual({
      requested: true,
      message: 'If eligible, check your email.',
      next_url: '/login',
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/register?token=invite%20%2F%20secret', {
      method: 'POST',
      credentials: 'same-origin',
      signal: undefined,
      headers: { 'X-CSRFToken': 'csrf-value', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  })

  test('requests and completes password reset through the CSRF-backed API', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ requested: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ reset: true, next_url: '/login' }) })
    vi.stubGlobal('fetch', fetchMock)
    document.head.innerHTML = '<meta name="csrf-token" content="csrf-value">'

    await expect(requestPasswordReset('guest@example.com')).resolves.toEqual({ requested: true })
    await expect(
      resetPassword('opaque/token', {
        password: 'long-password',
        confirm_password: 'long-password',
      }),
    ).resolves.toEqual({ reset: true, next_url: '/login' })

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/auth/password-reset/request',
      '/api/auth/password-reset/opaque%2Ftoken',
    ])
    expect(
      fetchMock.mock.calls.every(([, init]) => init.headers['X-CSRFToken'] === 'csrf-value'),
    ).toBe(true)
  })
})
