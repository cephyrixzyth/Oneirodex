import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { AuthApp } from './AuthApp'

const api = vi.hoisted(() => ({
  signIn: vi.fn(),
  registerAccount: vi.fn(),
  requestPasswordReset: vi.fn(),
  resetPassword: vi.fn(),
  setCsrfToken: vi.fn(),
  loadSetupState: vi.fn(),
  submitSetupStep: vi.fn(),
  errorFromResponse: vi.fn(async () => new Error('Request failed')),
}))

vi.mock('@oneirodex/ui', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@oneirodex/ui')>()),
  ...api,
}))

beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState({}, '', '/login')
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        csrf_token: 'csrf-test',
        oidc_enabled: true,
        oidc_display_name: 'Household SSO',
      }),
    })),
  )
})

test('login direct entry loads CSRF state and submits credentials through the API', async () => {
  api.signIn.mockResolvedValue({ next_url: '/library' })
  const navigate = vi.fn()
  render(<AuthApp navigate={navigate} />)
  expect(await screen.findByRole('heading', { name: 'Sign in to Oneirodex' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Sign in' }).closest('form')).toHaveAttribute(
    'novalidate',
  )
  expect(api.setCsrfToken).toHaveBeenCalledWith('csrf-test')
  expect(screen.getByRole('link', { name: 'Household SSO' })).toHaveAttribute('href', '/login/oidc')
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'member' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  await waitFor(() =>
    expect(api.signIn).toHaveBeenCalledWith(
      { username: 'member', password: 'secret-password' },
      { next: undefined },
    ),
  )
  expect(navigate).toHaveBeenCalledWith('/library')
})

test('empty login credentials show accessible required-field feedback without an API request', async () => {
  render(<AuthApp />)
  fireEvent.click(await screen.findByRole('button', { name: 'Sign in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Please enter your username and password.',
  )
  expect(api.signIn).not.toHaveBeenCalled()
})

test('login with only a username identifies the missing password without clearing the username', async () => {
  render(<AuthApp />)
  const username = await screen.findByLabelText('Username') as HTMLInputElement
  fireEvent.change(username, { target: { value: 'member' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Please enter your password.')
  expect(username).toHaveValue('member')
  expect(api.signIn).not.toHaveBeenCalled()
})

test('failed login displays the error and clears both credential fields', async () => {
  api.signIn.mockRejectedValue(
    new Error('Invalid username or password. USERNAMES ARE CASE SENSITIVE!'),
  )
  render(<AuthApp />)
  const username = await screen.findByLabelText('Username') as HTMLInputElement
  const password = screen.getByLabelText('Password') as HTMLInputElement
  fireEvent.change(username, { target: { value: 'ParityAdmin' } })
  fireEvent.change(password, { target: { value: 'wrong-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Invalid username or password. USERNAMES ARE CASE SENSITIVE!',
  )
  await waitFor(() => {
    expect(username).toHaveValue('')
    expect(password).toHaveValue('')
  })
})

test('registration preserves invite token and shows the generic account request response', async () => {
  window.history.replaceState({}, '', '/register?token=invite-token')
  api.registerAccount.mockResolvedValue({
    requested: true,
    message: 'If eligible, check your email.',
    next_url: '/login',
  })
  render(<AuthApp />)
  fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'new-member' } })
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'new@example.com' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
  expect(await screen.findByRole('heading', { name: 'Request received' })).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('If eligible, check your email.')
  expect(api.registerAccount).toHaveBeenCalledWith(
    { username: 'new-member', email: 'new@example.com', password: 'secret-password' },
    { inviteToken: 'invite-token' },
  )
})

test('reset request uses the generic recovery message', async () => {
  window.history.replaceState({}, '', '/reset_password_request')
  api.requestPasswordReset.mockResolvedValue({
    requested: true,
    message: 'If the account exists, instructions were sent.',
  })
  render(<AuthApp />)
  fireEvent.change(await screen.findByLabelText('Email'), {
    target: { value: 'member@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Send reset instructions' }))
  expect(await screen.findByRole('status')).toHaveTextContent(
    'If the account exists, instructions were sent.',
  )
  expect(api.requestPasswordReset).toHaveBeenCalledWith('member@example.com')
})

test('expired or invalid confirmation links surface an alert and keep the back link', async () => {
  window.history.replaceState({}, '', '/confirm/bad-token')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).startsWith('/api/auth/confirm/')) return { ok: false } as Response
      return {
        ok: true,
        json: async () => ({ csrf_token: 'csrf-test', oidc_enabled: false }),
      } as Response
    }),
  )
  render(<AuthApp />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Request failed')
  expect(screen.getByRole('link', { name: 'Back to sign in' })).toHaveAttribute('href', '/login')
})

test('first-run direct entry loads the active step and submits it to the transition API', async () => {
  window.history.replaceState({}, '', '/setup')
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 1,
    platforms: [],
    settings: {},
  })
  api.submitSetupStep.mockResolvedValue({ step: 2, next_url: '/setup/smtp' })
  const navigate = vi.fn()
  render(<AuthApp navigate={navigate} />)
  expect(await screen.findByRole('heading', { name: 'Create administrator' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Administrator username'), {
    target: { value: 'setup_admin' },
  })
  fireEvent.change(screen.getByLabelText('Administrator email'), {
    target: { value: 'setup@example.com' },
  })
  fireEvent.change(screen.getByLabelText('Password'), {
    target: { value: 'correct horse battery' },
  })
  fireEvent.change(screen.getByLabelText('Confirm password'), {
    target: { value: 'correct horse battery' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  await waitFor(() =>
    expect(api.submitSetupStep).toHaveBeenCalledWith({
      step: 1,
      skip: false,
      username: 'setup_admin',
      email: 'setup@example.com',
      password: 'correct horse battery',
      confirm_password: 'correct horse battery',
    }),
  )
  expect(navigate).toHaveBeenCalledWith('/setup/smtp')
})

test('the IGDB skip action bypasses required credential fields and advances setup', async () => {
  window.history.replaceState({}, '', '/setup/igdb')
  api.loadSetupState.mockResolvedValue({
    complete: false,
    required: true,
    step: 4,
    platforms: [],
    settings: {},
  })
  api.submitSetupStep.mockResolvedValue({ step: 5, next_url: '/setup/integrations' })
  const navigate = vi.fn()
  render(<AuthApp navigate={navigate} />)

  expect(await screen.findByRole('heading', { name: 'IGDB matching' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Skip this step' }))

  await waitFor(() =>
    expect(api.submitSetupStep).toHaveBeenCalledWith({
      step: 4,
      skip: true,
      igdb_client_id: '',
      igdb_client_secret: '',
    }),
  )
  expect(navigate).toHaveBeenCalledWith('/setup/integrations')
})
