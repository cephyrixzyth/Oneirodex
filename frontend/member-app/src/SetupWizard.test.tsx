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
  expect(within(steamGroup).getByLabelText('API key')).toHaveAttribute('maxLength', '255')

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
