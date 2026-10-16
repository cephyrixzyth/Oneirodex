import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { FeaturesPage } from './FeaturesPage'
import { getJson, putJson, postJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn(), postJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const preferences = {
  enable_arr_module: true,
  enable_ai_assist: true,
  enable_malware_scan: true,
  enable_game_updates: true,
  enable_game_extras: true,
  attract_mode_enabled: false,
  allow_children_in_household_lobby: false,
}
const challenge = {
  enabled: true,
  env_enabled: false,
  db_enabled: true,
  url: 'http://127.0.0.1:8191',
  provider: 'trawl',
  max_tier: 5,
}
const state = {
  preferences,
  challenge,
  process: [{ key: 'ENABLE_REMOTE_PLAY', label: 'Remote play', on: false, opt_in: true }],
  scanner: {
    enabled: true,
    block_on_hit: true,
    heuristics: { enabled: true, block_on_match: true },
    clamav: { reachable: false },
    settings: { host: '127.0.0.1', port: 3310, socket_configured: false },
  },
  enabled: false,
  env_enabled: false,
  db_enabled: false,
  provider: 'off',
  hyperion_url: '',
  hyperion_token_configured: false,
  hyperion_priority: 50,
  ambient_accent_color: '255,128,32',
  ha_url: '',
  ha_token_configured: false,
  ha_light_entities: [],
  ha_play_scene: '',
  ha_stop_scene: '',
  reachable: false,
  last_error: null,
}

test('seven independent preferences save without process toggles or solver calls', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.mocked(putJson).mockResolvedValue({
    preferences: { ...preferences, enable_game_updates: false },
  })
  render(<FeaturesPage />)
  const checkbox = await screen.findByLabelText('Game updates folders')
  expect(screen.getAllByRole('checkbox')).toHaveLength(9)
  expect(screen.getByRole('region', { name: 'Process feature settings table' })).toBeInTheDocument()
  fireEvent.click(checkbox)
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
  expect(await screen.findByText('Feature preferences saved.')).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith('/api/admin/features/settings', {
    ...preferences,
    enable_game_updates: false,
  })
  expect(postJson).not.toHaveBeenCalled()
})

test('ambient lighting saves write-only credentials without testing the connector', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.mocked(putJson).mockResolvedValue({
    ...state,
    enabled: true,
    db_enabled: true,
    provider: 'hyperion',
    hyperion_url: 'http://127.0.0.1:8090',
    hyperion_token_configured: true,
  })
  render(<FeaturesPage />)
  const provider = await screen.findByLabelText('Provider')
  fireEvent.change(provider, { target: { value: 'hyperion' } })
  fireEvent.change(screen.getByLabelText('Hyperion URL'), {
    target: { value: 'http://127.0.0.1:8090' },
  })
  fireEvent.change(screen.getByLabelText('Hyperion token'), { target: { value: 'review-token' } })
  fireEvent.click(screen.getByLabelText('Enable in database settings'))
  fireEvent.click(screen.getByRole('button', { name: 'Save lighting settings' }))
  await screen.findByText('Ambient-lighting settings saved. Credentials remain stored securely.')
  expect(putJson).toHaveBeenCalledWith(
    '/api/admin/ambient-lighting/config',
    expect.objectContaining({
      enabled: true,
      provider: 'hyperion',
      hyperion_url: 'http://127.0.0.1:8090',
      hyperion_token: 'review-token',
    }),
  )
  expect(postJson).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Hyperion token')).toHaveValue('')
})

test('dirty solver cannot test; save never probes and test requires explicit action', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.mocked(putJson).mockResolvedValue({ challenge: { ...challenge, max_tier: 6 } })
  vi.mocked(postJson).mockResolvedValue({ result: { probe_ok: true } })
  render(<FeaturesPage />)
  const tier = await screen.findByLabelText('Maximum solver tier')
  fireEvent.change(tier, { target: { value: '6' } })
  expect(screen.getByRole('button', { name: 'Test solver' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save solver settings' }))
  expect(await screen.findByText(/Solver settings saved/)).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith('/api/admin/features/challenge', {
    enabled: true,
    url: challenge.url,
    provider: 'trawl',
    max_tier: 6,
  })
  expect(postJson).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Test solver' }))
  expect(await screen.findByText('Solver connection successful.')).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/api/admin/features/challenge/test')
})

test('load failure retries; failed save retains draft and blocked controls recover', async () => {
  let featureLoad = 0
  vi.mocked(getJson).mockImplementation((url) => {
    if (url === '/api/admin/features/settings' && featureLoad++ === 0)
      return Promise.reject(new Error('Settings unavailable'))
    return Promise.resolve(state)
  })
  vi.mocked(putJson).mockRejectedValue(new Error('Save unavailable'))
  render(<FeaturesPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Settings unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading settings' }))
  const checkbox = await screen.findByLabelText('Game updates folders')
  fireEvent.click(checkbox)
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save unavailable')
  expect(checkbox).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Save preferences' })).toBeEnabled()
})

test('pending mutation blocks other saves/tests and repeated submit', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  let finish!: (value: any) => void
  vi.mocked(putJson).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    }),
  )
  render(<FeaturesPage />)
  const button = await screen.findByRole('button', { name: 'Save preferences' })
  fireEvent.click(button)
  fireEvent.click(button)
  expect(putJson).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Save solver settings' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Test solver' })).toBeDisabled()
  finish({ preferences })
  await waitFor(() => expect(button).toBeEnabled())
})
