import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { IgdbSettingsPage } from './IgdbSettingsPage'
import { getJson, putJson, postJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn(), postJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const settings = { igdb_client_id: 'review-client', secret_present: true, last_tested: null }

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
  fireEvent.change(secret, { target: { value: 'new-test-secret' } })
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
    igdb_client_id: 'review-client',
    igdb_client_secret: 'new-test-secret',
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
  expect(await screen.findByLabelText('Client ID')).toHaveValue('review-client')
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeEnabled()
})

test('failed save retains draft; missing saved secret prevents test', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: { ...settings, secret_present: false } })
  vi.mocked(putJson).mockRejectedValue(new Error('Save unavailable'))
  render(<IgdbSettingsPage />)
  const secret = await screen.findByLabelText('Client secret')
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled()
  fireEvent.change(secret, { target: { value: 'draft-test-secret' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save unavailable')
  expect(secret).toHaveValue('draft-test-secret')
  expect(screen.getByRole('link', { name: 'Twitch Developer Console' })).toHaveAttribute(
    'rel',
    'noopener noreferrer',
  )
})
