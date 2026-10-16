import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { getJson, putJson } from '../api/adminApi'
import { OidcSettingsPanel } from './OidcSettingsPanel'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const settings = {
  oidc_enabled: false,
  oidc_display_name: 'Sign in with SSO',
  oidc_issuer_url: '',
  oidc_client_id: '',
  oidc_client_secret_configured: true,
  oidc_redirect_uri: '',
  oidc_scopes: 'openid email profile',
  oidc_role_claim: 'groups',
  oidc_role_map: { admin: 'admin', child: 'child' },
}
const response = {
  settings,
  readiness: { ready: false, message: 'OIDC is not ready.', missing: ['issuer URL'] },
}
test('loads safe config, shows secret presence only, and saves without echoing secrets', async () => {
  vi.mocked(getJson).mockResolvedValue(response)
  vi.mocked(putJson).mockResolvedValue(response)
  render(<OidcSettingsPanel />)
  expect(await screen.findByText('OIDC is not ready.')).toBeInTheDocument()
  expect(screen.getByPlaceholderText('Saved; leave blank to keep it')).toHaveValue('')
  fireEvent.change(screen.getByLabelText('Issuer URL'), {
    target: { value: 'https://id.example.test' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save OIDC settings' }))
  await waitFor(() => expect(putJson).toHaveBeenCalled())
  expect(putJson).toHaveBeenCalledWith(
    '/api/admin/integrations/oidc',
    expect.objectContaining({ oidc_client_secret: '' }),
  )
  expect(vi.mocked(putJson).mock.calls[0][1]).not.toHaveProperty('oidc_client_secret_configured')
})
test('invalid role map is announced and failed saves retain draft values', async () => {
  vi.mocked(getJson).mockResolvedValue(response)
  vi.mocked(putJson).mockRejectedValue(new Error('Save unavailable'))
  render(<OidcSettingsPanel />)
  const roleMap = await screen.findByLabelText('Role map (JSON)')
  fireEvent.change(roleMap, { target: { value: '{bad json' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save OIDC settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Role map must be valid JSON.')
  expect(putJson).not.toHaveBeenCalled()
  fireEvent.change(roleMap, { target: { value: '{"admin":"admin"}' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save OIDC settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save unavailable')
  expect(roleMap).toHaveValue('{"admin":"admin"}')
})
test('failed loading blocks edits and offers Retry', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Config unavailable'))
    .mockResolvedValue(response)
  render(<OidcSettingsPanel />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Config unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading OIDC settings' }))
  expect(await screen.findByText('OIDC is not ready.')).toBeInTheDocument()
  expect(getJson).toHaveBeenCalledTimes(2)
})

test('OIDC native page renders as its own settings route', async () => {
  const { OidcSettingsPage } = await import('./OidcSettingsPage')
  const { MemoryRouter, Route, Routes } = await import('react-router-dom')
  vi.mocked(getJson).mockResolvedValue(response)
  render(
    <MemoryRouter initialEntries={['/admin/integrations/oidc']}>
      <Routes>
        <Route path="/admin/integrations/oidc" element={<OidcSettingsPage />} />
      </Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('heading', { name: 'OIDC / SSO', level: 1 })).toBeInTheDocument()
  expect(screen.getByLabelText('Issuer URL')).toBeInTheDocument()
})
