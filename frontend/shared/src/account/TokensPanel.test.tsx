import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'

import { TokensPanel } from './TokensPanel.js'

const api = vi.hoisted(() => ({
  createToken: vi.fn(),
  extractOneTimeSecret: vi.fn((data: { secret?: string }) => data.secret ?? ''),
  listTokens: vi.fn(),
  revokeToken: vi.fn(),
}))

vi.mock('../tokensApi.js', () => api)

beforeEach(() => vi.clearAllMocks())

test('Done clears the one-time secret and returns focus to token name', async () => {
  api.listTokens.mockResolvedValue({ tokens: [] })
  api.createToken.mockResolvedValue({ secret: 'gt_test-one-time-secret' })
  render(<TokensPanel />)

  const name = await screen.findByRole('textbox', { name: 'Token name' })
  fireEvent.change(name, { target: { value: 'Living room' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create token' }))

  const done = await screen.findByRole('button', { name: 'Done' })
  expect(screen.getByText('gt_test-one-time-secret')).toBeInTheDocument()
  done.focus()
  fireEvent.click(done)

  await waitFor(() => expect(screen.queryByText('gt_test-one-time-secret')).toBeNull())
  expect(name).toHaveFocus()
})

test('announces a token-list request failure', async () => {
  api.listTokens.mockRejectedValueOnce(new Error('Temporary service failure'))
  render(<TokensPanel />)

  expect(await screen.findByRole('alert')).toHaveTextContent('Temporary service failure')
})

test('shows a create failure without exposing a one-time secret', async () => {
  api.listTokens.mockResolvedValue({ tokens: [] })
  api.createToken.mockRejectedValue(new Error('Create unavailable'))
  render(<TokensPanel />)

  fireEvent.change(await screen.findByRole('textbox', { name: 'Token name' }), {
    target: { value: 'Living room' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Create token' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Create unavailable')
  expect(screen.queryByText(/gt_/)).toBeNull()
})

test('keeps a populated token visible when revocation fails', async () => {
  api.listTokens.mockResolvedValue({
    tokens: [
      {
        id: 12,
        name: 'Living room',
        token_prefix: 'gt_ab12',
        created_at: '2026-01-01T00:00:00Z',
      },
    ],
  })
  api.revokeToken.mockRejectedValue(new Error('Revoke unavailable'))
  render(<TokensPanel />)

  expect(await screen.findByText('Living room')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Revoke' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Revoke unavailable')
  expect(screen.getByText('Living room')).toBeInTheDocument()
})
