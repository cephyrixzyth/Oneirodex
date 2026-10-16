import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'

import { UsersPage } from './UsersPage'

vi.mock('../utils/toast', () => ({
  showToast: vi.fn(),
}))

const ADA = {
  id: 1,
  name: 'Ada',
  email: 'ada@example.com',
  has_email: true,
  role: 'admin',
  state: true,
  is_email_verified: true,
}

function mockFetch(users = [ADA], putOk = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      if (String(url).includes('/admin/api/users') && !String(url).includes('/admin/api/user/')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({ users }),
        }
      }
      if (String(url).includes('/admin/api/user/') && init.method === 'PUT') {
        return {
          ok: putOk,
          status: putOk ? 200 : 400,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () =>
            putOk ? { ok: true, error: null } : { ok: false, error: 'Cannot modify your own role' },
        }
      }
      throw new Error(`unexpected fetch ${url} ${init.method || 'GET'}`)
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

test('the roster is the editor — no classic-editor dest (W33-11)', async () => {
  mockFetch()
  render(<UsersPage />)
  expect(await screen.findByText('Ada')).toBeInTheDocument()
  expect(screen.queryByText(/classic/i)).toBeNull()
  expect(screen.getByRole('button', { name: 'Edit Ada account' })).toBeInTheDocument()
})

test('Edit saves role through the existing user API', async () => {
  mockFetch()
  const user = userEvent.setup()
  render(<UsersPage />)
  await screen.findByText('Ada')

  await user.click(screen.getByRole('button', { name: 'Edit Ada account' }))
  expect(screen.getByRole('heading', { name: 'Edit Ada' })).toBeInTheDocument()

  await user.selectOptions(screen.getByLabelText('Role'), 'librarian')
  await user.click(screen.getByRole('button', { name: 'Save' }))

  expect(fetch).toHaveBeenCalledWith(
    '/admin/api/user/1',
    expect.objectContaining({
      method: 'PUT',
      body: expect.stringMatching(/"role":"librarian"/),
    }),
  )
})

test('failed save uses PageStatus', async () => {
  mockFetch([ADA], false)
  const user = userEvent.setup()
  render(<UsersPage />)
  await screen.findByText('Ada')

  await user.click(screen.getByRole('button', { name: 'Edit Ada account' }))
  await user.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Cannot modify your own role')
})

test('Invites and Support sit in the top bar when the slot exists (W33-9)', async () => {
  const slot = document.createElement('div')
  slot.id = 'od-admin-topbar-slot'
  document.body.appendChild(slot)
  mockFetch()
  try {
    render(<UsersPage />)
    await screen.findByText('Ada')
    expect(within(slot).getByRole('link', { name: 'Invites' })).toHaveAttribute(
      'href',
      '/admin/invites',
    )
    const links = within(slot)
      .getAllByRole('link')
      .map((link) => link.textContent!.trim())
    expect(links).toEqual(['Invites', 'Support inbox', 'Invite quotas'])
    // Topbar actions are portaled; Create user stays on the page (not a topbar row).
    expect(within(slot).queryByRole('button', { name: 'Create user' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Create user' })).toBeInTheDocument()
  } finally {
    slot.remove()
  }
})
