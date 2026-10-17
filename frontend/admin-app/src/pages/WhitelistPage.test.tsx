import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { WhitelistPage } from './WhitelistPage'
import { confirmAction } from '@oneirodex/ui'
import { getJson, postJson, deleteJson } from '../api/adminApi'

vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn(), deleteJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (original) => ({
  ...(await original<typeof import('@oneirodex/ui')>()),
  confirmAction: vi.fn(),
}))
afterEach(() => vi.resetAllMocks())

test('adds email and renders registered status and named remove action', async () => {
  vi.mocked(getJson).mockResolvedValue({
    entries: [{ id: 1, email: 'person@example.com', is_registered: true }],
  })
  vi.mocked(postJson).mockResolvedValue({ ok: true })
  render(<WhitelistPage />)
  expect(await screen.findByText('Registered')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Registration whitelist table' })).toHaveAttribute(
    'tabindex',
    '0',
  )
  fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'new@example.com' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add email' }))
  expect(await screen.findByText('Email added to the whitelist.')).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/admin/api/whitelist', { email: 'new@example.com' })
})

test('cancel leaves the entry, confirmed removal uses the existing endpoint', async () => {
  vi.mocked(getJson).mockResolvedValue({
    entries: [{ id: 1, email: 'person@example.com', is_registered: false }],
  })
  vi.mocked(deleteJson).mockResolvedValue({ ok: true })
  vi.mocked(confirmAction).mockResolvedValueOnce(false).mockResolvedValueOnce(true)
  render(<WhitelistPage />)
  const remove = await screen.findByRole('button', {
    name: 'Remove person@example.com from whitelist',
  })
  fireEvent.click(remove)
  await vi.waitFor(() => expect(confirmAction).toHaveBeenCalledTimes(1))
  expect(deleteJson).not.toHaveBeenCalled()
  fireEvent.click(remove)
  expect(await screen.findByText('Whitelist entry removed.')).toBeInTheDocument()
  expect(deleteJson).toHaveBeenCalledWith('/admin/whitelist/1')
})

test('restores legacy form value and field error in the React page', async () => {
  vi.mocked(getJson).mockResolvedValue({ entries: [] })
  const legacyState = document.createElement('div')
  legacyState.id = 'od-whitelist-form-state'
  legacyState.dataset.email = 'not-an-email'
  legacyState.dataset.error = 'Invalid email address.'
  document.body.append(legacyState)

  render(<WhitelistPage />)

  expect(await screen.findByLabelText('Email address')).toHaveValue('not-an-email')
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email address.')
  expect(document.getElementById('od-whitelist-form-state')).toBeNull()
})
