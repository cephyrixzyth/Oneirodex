import { fireEvent, render, screen, within } from '@testing-library/react'

import { InvitesPage } from './InvitesPage'

function mockFetch(body: any) {
  return vi.fn(async (): Promise<any> => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => body,
  }))
}

/**
 * The Invites readiness strip (UID-014).
 *
 * The totals it shows are summed in the component, and the summing has to
 * survive rows the API returns without a quota — an account that has never had
 * one omits the field rather than sending zero. `undefined` in a running total
 * poisons it to NaN, and "NaN unused tokens" is worse than no strip at all,
 * so that guard is what these pin.
 */
test('sums invite totals across users', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch({
    users: [
      { user_id: 'a', name: 'Ada', role: 'admin', invite_quota: 10, unused_invites: 3 },
      { user_id: 'b', name: 'Brin', role: 'user', invite_quota: 5, unused_invites: 2 },
    ],
  }) as unknown as typeof globalThis.fetch
  try {
    render(<InvitesPage />)

    const strip = await screen.findByLabelText('Invites')
    expect(within(strip).getByText('5')).toBeInTheDocument() // 3 + 2 unused
    expect(within(strip).getByText('15')).toBeInTheDocument() // 10 + 5 quota
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a user with no quota fields counts as zero, not NaN', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch({
    users: [
      { user_id: 'a', name: 'Ada', role: 'admin', invite_quota: 4, unused_invites: 1 },
      // No invite_quota / unused_invites at all — the shape the API returns for
      // an account that has never been given a quota.
      { user_id: 'b', name: 'Brin', role: 'user' },
    ],
  }) as unknown as typeof globalThis.fetch
  try {
    render(<InvitesPage />)

    const strip = await screen.findByLabelText('Invites')
    expect(within(strip).queryByText(/NaN/)).toBeNull()
    expect(within(strip).getByText('4')).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('warns when nobody can invite anyone', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch({
    users: [{ user_id: 'a', name: 'Ada', role: 'admin', invite_quota: 2, unused_invites: 0 }],
  }) as unknown as typeof globalThis.fetch
  try {
    render(<InvitesPage />)

    // Zero unused tokens means invites are effectively closed for the whole
    // household — a fact the per-user table states only by making you add up
    // a column yourself.
    const strip = await screen.findByLabelText('Invites')
    expect(within(strip).getByText('Unused tokens')).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('posts a signed quota adjustment and announces success', async () => {
  const originalFetch = globalThis.fetch
  const fetchMock = vi.fn(async (input: any, init: any): Promise<any> => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () =>
      init?.method === 'POST'
        ? { ok: true, invite_quota: 3 }
        : { users: [{ user_id: 'a', name: 'Ada', invite_quota: 5 }] },
    text: async () =>
      JSON.stringify(
        init?.method === 'POST'
          ? { ok: true, invite_quota: 3 }
          : { users: [{ user_id: 'a', name: 'Ada', invite_quota: 5 }] },
      ),
  }))
  globalThis.fetch = fetchMock as typeof fetch
  try {
    render(<InvitesPage />)
    await screen.findByRole('option', { name: 'Ada' })
    fireEvent.change(screen.getByLabelText('Member'), { target: { value: 'a' } })
    fireEvent.change(screen.getByLabelText('Quota adjustment'), { target: { value: '-2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Adjust quota' }))
    expect(await screen.findByText('Quota updated to 3.')).toBeInTheDocument()
    const mutation = fetchMock.mock.calls.find((call) => call[1]?.method === 'POST')!
    expect(mutation[0]).toBe('/admin/api/invites/quota')
    expect(JSON.parse(mutation[1].body)).toEqual({ user_id: 'a', invites_number: -2 })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('offers retry after invite data fails to load', async () => {
  const originalFetch = globalThis.fetch
  let attempts = 0
  globalThis.fetch = vi.fn(async (): Promise<any> => {
    attempts += 1
    if (attempts === 1) {
      return {
        ok: false,
        status: 503,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ code: 'service_unavailable', detail: 'Try again.' }),
        text: async () => JSON.stringify({ code: 'service_unavailable', detail: 'Try again.' }),
      }
    }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ users: [{ user_id: 'a', name: 'Ada', role: 'user', invite_quota: 2 }] }),
      text: async () =>
        JSON.stringify({ users: [{ user_id: 'a', name: 'Ada', role: 'user', invite_quota: 2 }] }),
    }
  }) as unknown as typeof globalThis.fetch
  try {
    render(<InvitesPage />)
    const retry = await screen.findByRole('button', { name: 'Retry loading invites' })
    expect(screen.getByRole('heading', { name: 'Invites' })).toBeInTheDocument()
    fireEvent.click(retry)
    expect(await screen.findByRole('option', { name: 'Ada' })).toBeInTheDocument()
    expect(attempts).toBe(2)
  } finally {
    globalThis.fetch = originalFetch
  }
})
