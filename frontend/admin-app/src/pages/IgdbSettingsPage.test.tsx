import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { IgdbSettingsPage } from './IgdbSettingsPage'
import { getJson, postJson } from '../api/adminApi'
import { showToast } from '../utils/toast'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn() }))
vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const settings = {
  igdb_client_id: 'review-client-01234567',
  secret_present: true,
  last_tested: null,
}

test('matches the legacy page title and places instructions before credentials', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings })
  render(<IgdbSettingsPage />)

  expect(await screen.findByRole('heading', { name: 'IGDB API Settings' })).toBeInTheDocument()
  await waitFor(() => expect(document.title).toBe('IGDB metadata · Oneirodex Admin'))
  const instructions = screen.getByText('Show Instructions').closest('details')
  const form = screen.getByRole('button', { name: 'Save Settings' }).closest('form')
  expect(instructions).not.toBeNull()
  expect(instructions).not.toHaveAttribute('open')
  expect(form).not.toBeNull()
  expect(form).toHaveClass('od-igdb-form')
  expect(form).not.toHaveClass('od-admin-panel')
  expect(instructions!.compareDocumentPosition(form!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByLabelText('Client Secret')).toHaveAttribute(
    'placeholder',
    'Saved. Leave blank to keep it',
  )
  expect(screen.getByRole('group', { name: 'API credentials' })).toBeInTheDocument()
  fireEvent.click(instructions!.querySelector('summary')!)
  expect(
    screen.getByRole('heading', { name: 'How to Get Your IGDB API Credentials' }),
  ).toBeInTheDocument()
  expect(
    instructions!.querySelector('.od-igdb-instructions__body > ol')?.querySelectorAll(':scope > li'),
  ).toHaveLength(6)
  expect(screen.getByText(/free tier includes 4 requests per second and 500k requests per month/)).toBeInTheDocument()
})

test('saved secret is never populated; dirty drafts can test saved settings and save retains the entered secret', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings })
  vi.mocked(postJson).mockResolvedValue({ status: 'success', message: 'saved' })
  render(<IgdbSettingsPage />)
  const secret = await screen.findByLabelText('Client Secret')
  expect(secret).toHaveValue('')
  expect(secret).toHaveAttribute('type', 'password')
  fireEvent.change(secret, { target: { value: 'new-test-secret-value' } })
  fireEvent.click(screen.getByRole('button', { name: 'Toggle password visibility' }))
  expect(secret).toHaveAttribute('type', 'text')
  expect(screen.getByRole('button', { name: 'Toggle password visibility' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(screen.getByRole('button', { name: 'Test Connection' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
  expect((await screen.findAllByText('IGDB settings saved successfully')).length).toBeGreaterThan(0)
  expect(postJson).toHaveBeenCalledWith('/admin/igdb_settings', {
    igdb_client_id: 'review-client-01234567',
    igdb_client_secret: 'new-test-secret-value',
  })
  expect(secret).toHaveValue('new-test-secret-value')
  expect(secret).toHaveAttribute('type', 'text')
  expect(screen.getByRole('button', { name: 'Toggle password visibility' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(screen.getByText(/A secret is saved/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }))
  expect(await screen.findByText('IGDB API test successful')).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/admin/test_igdb')
})

test('load failure guards saving and retry restores safe state', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Config unavailable'))
    .mockResolvedValueOnce({ settings })
  render(<IgdbSettingsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Config unavailable')
  expect(screen.getByRole('button', { name: 'Save Settings' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading settings' }))
  expect(await screen.findByLabelText('Client ID *')).toHaveValue('review-client-01234567')
  expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled()
})

test('failed save retains draft; missing credentials reach the legacy test endpoint', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: { ...settings, secret_present: false } })
  vi.mocked(postJson).mockRejectedValue(new Error('Save unavailable'))
  render(<IgdbSettingsPage />)
  const secret = await screen.findByLabelText('Client Secret')
  expect(screen.getByRole('button', { name: 'Test Connection' })).toBeEnabled()
  vi.mocked(postJson).mockRejectedValueOnce(new Error('IGDB settings not configured'))
  fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }))
  await waitFor(() =>
    expect(showToast).toHaveBeenCalledWith(
      'IGDB API test failed: IGDB settings not configured',
      'error',
    ),
  )
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/admin/test_igdb')
  fireEvent.change(secret, { target: { value: 'draft-test-secret-value' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
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
  const clientId = await screen.findByLabelText('Client ID *')
  const secret = screen.getByLabelText('Client Secret')
  fireEvent.change(clientId, { target: { value: 'x'.repeat(19) } })
  fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Client ID and Secret must be at least 20 characters long',
  )
  expect(clientId).toHaveAttribute('aria-invalid', 'true')
  expect(secret).toHaveAttribute('aria-invalid', 'false')
  expect(clientId).toHaveAttribute('minlength', '20')
  expect(clientId).toHaveAttribute('maxlength', '50')
  expect(secret).toHaveAttribute('minlength', '20')
  expect(secret).toHaveAttribute('maxlength', '50')
  expect(postJson).not.toHaveBeenCalled()
})

test('marks a non-empty short replacement secret invalid but leaves a blank secret valid', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: { ...settings, secret_present: false } })
  render(<IgdbSettingsPage />)
  const clientId = await screen.findByLabelText('Client ID *')
  const secret = screen.getByLabelText('Client Secret')
  fireEvent.change(clientId, { target: { value: 'c'.repeat(20) } })
  fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Client ID and Secret must be at least 20 characters long',
  )
  expect(clientId).toHaveAttribute('aria-invalid', 'false')
  expect(secret).toHaveAttribute('aria-invalid', 'false')
  expect(postJson).not.toHaveBeenCalled()

  fireEvent.change(secret, { target: { value: 's'.repeat(19) } })
  fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
  expect(secret).toHaveAttribute('aria-invalid', 'true')
  expect(postJson).not.toHaveBeenCalled()
})

test('allows a blank replacement when the saved secret is being retained', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings })
  vi.mocked(postJson).mockResolvedValue({ status: 'success', message: 'saved' })
  render(<IgdbSettingsPage />)
  await screen.findByLabelText('Client ID *')
  expect(screen.getByLabelText('Client Secret')).toHaveValue('')
  fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
  expect(await screen.findByText('IGDB settings saved successfully')).toBeInTheDocument()
  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/admin/igdb_settings', {
      igdb_client_id: settings.igdb_client_id,
      igdb_client_secret: '',
    }),
  )
})

test('legacy save preserves whitespace in an otherwise valid client ID', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings })
  vi.mocked(postJson).mockResolvedValue({ status: 'success', message: 'saved' })
  render(<IgdbSettingsPage />)
  const clientId = await screen.findByLabelText('Client ID *')
  const submittedId = ` ${'x'.repeat(20)} `
  fireEvent.change(clientId, { target: { value: submittedId } })
  fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
  expect((await screen.findAllByText('IGDB settings saved successfully')).length).toBeGreaterThan(0)
  expect(postJson).toHaveBeenCalledWith('/admin/igdb_settings', {
    igdb_client_id: submittedId,
    igdb_client_secret: '',
  })
})
