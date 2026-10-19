import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'

import { createInvite, listInvites, revokeInvite } from '../accountApi.js'
import { InvitesPanel } from './InvitesPanel'

vi.mock('../accountApi.js', () => ({
  createInvite: vi.fn(),
  listInvites: vi.fn(),
  revokeInvite: vi.fn(),
}))

const invite = {
  token: 'fixture-invite-token',
  email: null,
  url: 'https://oneirodex.invalid/register?token=fixture-invite-token',
  expires_at: '2026-10-20T12:00:00Z',
  expired: false,
}

const emptyState = {
  invites: [],
  quota: 5,
  remaining: 5,
  unlimited: false,
  smtp_enabled: false,
  ttl_hours: 48,
  site_url_configured: false,
}

beforeEach(() => {
  vi.clearAllMocks()
})

test('creates a link without email, then refreshes and exposes it for copying', async () => {
  vi.mocked(listInvites)
    .mockResolvedValueOnce(emptyState)
    .mockResolvedValueOnce({ ...emptyState, invites: [invite], remaining: 4 })
  vi.mocked(createInvite).mockResolvedValue({ invite, emailed: false, remaining: 4, unlimited: false })

  render(<InvitesPanel />)

  expect(await screen.findByRole('button', { name: 'Create invite link' })).toBeEnabled()
  expect(screen.getByText(/Email is not configured on this server/)).toBeInTheDocument()
  expect(screen.getByText(/Links use the address you are browsing from/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Create invite link' }))

  await waitFor(() => expect(createInvite).toHaveBeenCalledWith({}))
  expect(await screen.findByText('Invite created. Copy the link below and pass it on.')).toBeInTheDocument()
  expect(screen.getByText(invite.url)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Revoke' })).toBeInTheDocument()
  expect(listInvites).toHaveBeenCalledTimes(2)
})

test('revokes an outstanding invite and refreshes the empty state', async () => {
  vi.mocked(listInvites)
    .mockResolvedValueOnce({ ...emptyState, invites: [invite], remaining: 4 })
    .mockResolvedValueOnce(emptyState)
  vi.mocked(revokeInvite).mockResolvedValue({ ok: true })

  render(<InvitesPanel />)
  expect(await screen.findByText(invite.url)).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Revoke' }))

  await waitFor(() => expect(revokeInvite).toHaveBeenCalledWith(invite.token))
  expect(await screen.findByText('No open invites.')).toBeInTheDocument()
  expect(listInvites).toHaveBeenCalledTimes(2)
})

test('prevents creating another invite when the quota is exhausted', async () => {
  vi.mocked(listInvites).mockResolvedValue({ ...emptyState, remaining: 0 })

  render(<InvitesPanel />)

  expect(await screen.findByRole('button', { name: 'Create invite link' })).toBeDisabled()
  expect(createInvite).not.toHaveBeenCalled()
})
