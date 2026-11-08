import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { TokensPanel } from './TokensPanel.js'

const api = vi.hoisted(() => ({
  createToken: vi.fn(),
  extractOneTimeSecret: vi.fn((data: { secret?: string }) => data.secret ?? ''),
  listTokens: vi.fn(),
  revokeToken: vi.fn(),
}))

vi.mock('../tokensApi.js', () => api)

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
