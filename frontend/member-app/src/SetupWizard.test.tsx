import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { SetupWizard } from './SetupWizard'

const api = vi.hoisted(() => ({
  loadSetupState: vi.fn(),
  submitSetupStep: vi.fn(),
}))

vi.mock('@oneirodex/ui', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@oneirodex/ui')>()),
  ...api,
}))

beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState({}, '', '/setup/integrations')
})

test('admin setup keeps the v1.1.8 welcome and sign-in guidance', async () => {
  window.history.replaceState({}, '', '/setup')
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 1,
    platforms: [],
    settings: {},
  })
  render(<SetupWizard navigate={vi.fn()} />)

  expect(
    await screen.findByRole('heading', { name: 'Create your admin account' }),
  ).toBeInTheDocument()
  expect(
    screen.getByText('Oneirodex initial setup — one household admin to get started.'),
  ).toBeInTheDocument()
  expect(
    screen.getByText(
      'Local username and password is enough for home installs. Authentik / OIDC SSO is optional and can be enabled later under Admin → Integrations.',
    ),
  ).toBeInTheDocument()
  expect(screen.getByLabelText('Admin Username')).toBeRequired()
  expect(screen.getByLabelText('Admin Email')).toBeRequired()
  expect(screen.getByRole('button', { name: 'Next Step' })).toBeInTheDocument()
})

test('feature setup keeps the legacy Library and Modules groups', async () => {
  window.history.replaceState({}, '', '/setup/features')
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 3,
    platforms: [],
    settings: { features: {} },
  })
  render(<SetupWizard navigate={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Features' })).toBeInTheDocument()
  const library = screen.getByRole('group', { name: 'Library' })
  const modules = screen.getByRole('group', { name: 'Modules' })
  expect(within(library).getByLabelText('Game updates')).toBeInTheDocument()
  expect(within(library).getByLabelText('Game extras')).toBeInTheDocument()
  expect(within(library).getByLabelText('Attract mode')).toBeInTheDocument()
  expect(within(modules).getByLabelText('Arr / indexers')).toBeInTheDocument()
  expect(within(modules).getByLabelText('AI assist')).toBeInTheDocument()
  expect(within(modules).getByLabelText('Malware scanner')).toBeInTheDocument()
  expect(
    screen.getByText(
      'Authentication (OIDC/SSO) stays off — enable later under Admin → Integrations if needed.',
    ),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument()
})

test('metadata setup keeps the wide IGDB layout and full-width credential guide', async () => {
  window.history.replaceState({}, '', '/setup/igdb')
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 4,
    platforms: [],
    settings: {},
  })
  render(<SetupWizard navigate={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Connect game metadata' })).toBeInTheDocument()
  expect(document.querySelector('.auth-pilot__form--igdb')).toBeInTheDocument()
  expect(screen.getByLabelText('Client ID')).toBeInTheDocument()
  expect(screen.getByLabelText('Client Secret')).toBeInTheDocument()
  expect(screen.getByText('How do I get IGDB credentials?')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save IGDB and continue' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Skip and continue' })).toBeInTheDocument()
})

test('SMTP setup preserves v1.1.8 step labels and both actions', async () => {
  window.history.replaceState({}, '', '/setup/smtp')
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 2,
    platforms: [],
    settings: {},
  })
  const navigate = vi.fn()
  render(<SetupWizard navigate={navigate} />)

  expect(await screen.findByRole('heading', { name: 'Email (SMTP)' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next step' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Skip SMTP' })).toBeInTheDocument()
})

test('integrations setup matches provider groups and preserves explicit configure choices', async () => {
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 5,
    platforms: [],
    settings: {
      provider_keys: {},
      oidc: { issuer_url: '', client_id: '', secret_configured: false },
      enable_hltb_integration: false,
    },
  })
  api.submitSetupStep.mockResolvedValue({ step: 6, next_url: '/setup/library' })
  const navigate = vi.fn()
  render(<SetupWizard navigate={navigate} />)

  expect(await screen.findByRole('heading', { name: 'Choose API connections' })).toBeInTheDocument()
  const progress = screen.getByRole('navigation', { name: 'Setup progress' })
  expect(within(progress).getAllByText(/^[1-6] · /)).toHaveLength(6)
  expect(within(progress).getByText('5 · APIs')).toHaveAttribute('aria-current', 'step')
  expect(
    screen.getByText(
      'Secrets are saved in the local settings database and never filled back into this form. Leave a credential blank to keep an existing value.',
    ),
  ).toBeInTheDocument()
  expect(screen.getByText('Other optional services')).toBeInTheDocument()
  expect(screen.getByText('HowLongToBeat')).toBeInTheDocument()
  expect(screen.getByText('OIDC / SSO')).toBeInTheDocument()
  expect(document.querySelector('.auth-pilot__provider-grid')).toContainElement(
    screen.getByText('Steam Web API'),
  )

  const steam = screen.getByLabelText('Configure Steam ownership lookup')
  const steamGrid = screen.getByLabelText('Configure game artwork lookup')
  const steamGroup = steam.closest('fieldset')
  const steamGridGroup = steamGrid.closest('fieldset')
  if (
    !(steamGroup instanceof HTMLFieldSetElement) ||
    !(steamGridGroup instanceof HTMLFieldSetElement)
  )
    throw new Error('Provider controls must remain grouped in fieldsets.')
  for (const apiKeyInput of screen.getAllByLabelText('API key')) {
    expect(apiKeyInput).toHaveAttribute('maxLength', '255')
  }

  fireEvent.change(within(steamGroup).getByLabelText('API key'), {
    target: { value: 'unchecked-provider-key' },
  })
  fireEvent.click(steamGrid)
  fireEvent.change(within(steamGridGroup).getByLabelText('API key'), {
    target: { value: 'selected-provider-key' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save choices and continue' }))

  await waitFor(() =>
    expect(api.submitSetupStep).toHaveBeenCalledWith(
      expect.objectContaining({
        step: 5,
        skip: false,
        steam_web_api_key: 'unchecked-provider-key',
        configure_steam_web_api_key: false,
        steamgriddb_api_key: 'selected-provider-key',
        configure_steamgriddb_api_key: true,
      }),
    ),
  )
  expect(navigate).toHaveBeenCalledWith('/setup/library')
})

test('integrations setup skip action advances without saving the entered credentials', async () => {
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 5,
    platforms: [],
    settings: { provider_keys: {}, oidc: {} },
  })
  api.submitSetupStep.mockResolvedValue({ step: 6, next_url: '/setup/library' })
  const navigate = vi.fn()
  render(<SetupWizard navigate={navigate} />)

  await screen.findByRole('heading', { name: 'Choose API connections' })
  expect(screen.getByRole('button', { name: 'Skip API setup' })).toBeInTheDocument()
  fireEvent.change(screen.getAllByLabelText('API key')[0], {
    target: { value: 'skip-must-not-save' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Skip API setup' }))

  await waitFor(() =>
    expect(api.submitSetupStep).toHaveBeenCalledWith(
      expect.objectContaining({ step: 5, skip: true }),
    ),
  )
  expect(navigate).toHaveBeenCalledWith('/setup/library')
})

test('first library setup matches the create-and-scan action with a responsive field grid', async () => {
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 6,
    platforms: [{ key: 'PC_WINDOWS', label: 'PC Windows' }],
    settings: {},
  })
  const navigate = vi.fn()
  render(<SetupWizard navigate={navigate} />)

  expect(
    await screen.findByRole('heading', { name: 'Create your first library' }),
  ).toBeInTheDocument()
  expect(screen.getByText(/start its first scan/)).toBeInTheDocument()
  expect(screen.getByText(/Game files remain read-only/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Create library and start scan' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Finish without a library' })).toBeInTheDocument()
  expect(document.querySelector('.auth-pilot__form--library')).toBeInTheDocument()
})
