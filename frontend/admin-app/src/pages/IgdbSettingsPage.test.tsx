import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { IgdbSettingsPage } from './IgdbSettingsPage'
import { getJson, putJson, postJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn(), postJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const settings = { igdb_client_id: 'review-client-01234567', secret_present: true, last_tested: null }

test('saved secret is never populated; dirty drafts cannot test and save clears new secret', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings })
  vi.mocked(putJson).mockResolvedValue({ settings })
  vi.mocked(postJson).mockResolvedValue({
    settings: { ...settings, last_tested: '2026-10-10T00:00:00Z' },
  })
  render(<IgdbSettingsPage />)
  const secret = await screen.findByLabelText('Client secret')
  expect(secret).toHaveValue('')
  expect(secret).toHaveAttribute('type', 'password')
  fireEvent.change(secret, { target: { value: 'new-test-secret-value' } })
  fireEvent.click(screen.getByRole('button', { name: 'Show entered secret' }))
  expect(secret).toHaveAttribute('type', 'text')
  expect(screen.getByRole('button', { name: 'Hide entered secret' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('IGDB settings saved.')).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith('/api/admin/igdb/settings', {
    igdb_client_id: 'review-client-01234567',
    igdb_client_secret: 'new-test-secret-value',
  })
  expect(secret).toHaveValue('')
  expect(secret).toHaveAttribute('type', 'password')
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(await screen.findByText('IGDB connection successful.')).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/api/admin/igdb/test')
  expect(screen.getByText(/Last connection test:/)).toBeInTheDocument()
})

test('load failure guards saving and retry restores safe state', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Config unavailable'))
    .mockResolvedValueOnce({ settings })
  render(<IgdbSettingsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Config unavailable')
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading settings' }))
  expect(await screen.findByLabelText('Client ID')).toHaveValue('review-client-01234567')
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeEnabled()
})

test('failed save retains draft; missing saved secret prevents test', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: { ...settings, secret_present: false } })
  vi.mocked(putJson).mockRejectedValue(new Error('Save unavailable'))
  render(<IgdbSettingsPage />)
  const secret = await screen.findByLabelText('Client secret')
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled()
  fireEvent.change(secret, { target: { value: 'draft-test-secret-value' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save unavailable')
  expect(secret).toHaveValue('draft-test-secret-value')
  expect(screen.getByRole('link', { name: 'Twitch Developer Console' })).toHaveAttribute(
    'rel',
    'noopener noreferrer',
  )
})

test('blocks credentials under the legacy minimum before saving', async () => {
  vi.mocked(getJson).mockResolvedValue({
    settings: { igdb_client_id: '', secret_present: false, last_tested: null },
  })
  render(<IgdbSettingsPage />)
  const clientId = await screen.findByLabelText('Client ID')
  const secret = screen.getByLabelText('Client secret')
  fireEvent.change(clientId, { target: { value: 'x'.repeat(19) } })
  fireEvent.change(secret, { target: { value: 's'.repeat(19) } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Client ID and secret must be at least 20 characters long.',
  )
  expect(putJson).not.toHaveBeenCalled()
})

test('allows a blank replacement when the saved secret is being retained', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings })
  vi.mocked(putJson).mockResolvedValue({ settings })
  render(<IgdbSettingsPage />)
  await screen.findByLabelText('Client ID')
  expect(screen.getByLabelText('Client secret')).toHaveValue('')
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('IGDB settings saved.')).toBeInTheDocument()
  await waitFor(() =>
    expect(putJson).toHaveBeenCalledWith('/api/admin/igdb/settings', {
      igdb_client_id: settings.igdb_client_id,
      igdb_client_secret: '',
    }),
  )
})
