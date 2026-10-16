import { csrfHeaders } from './csrf.js'
import { errorFromResponse } from './envelopeError.js'

export interface LoginResult {
  next_url: string
}

export interface RegistrationResult {
  requested: true
  message: string
  next_url: string
}

export interface RegistrationCredentials {
  username: string
  email: string
  password: string
}

export interface PasswordResetResult {
  requested?: true
  reset?: true
  message?: string
  next_url?: string
}

export interface SetupState {
  complete: boolean
  required: boolean
  step: number | null
  platforms: Array<{ key: string; label: string }>
  settings: Record<string, unknown>
}

export async function loadSetupState(): Promise<SetupState> {
  const response = await fetch('/api/setup/state', { credentials: 'same-origin' })
  if (!response.ok) throw await errorFromResponse(response, 'Load setup')
  return response.json() as Promise<SetupState>
}

export async function submitSetupStep(payload: Record<string, unknown>): Promise<{
  step?: number
  complete?: boolean
  next_url?: string
  message?: string
}> {
  const response = await fetch('/api/setup/step', {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw await errorFromResponse(response, 'Save setup step')
  return response.json()
}

/** Establish the same browser session as the classic login form. */
export async function signIn(
  credentials: { username: string; password: string },
  { next, signal }: { next?: string; signal?: AbortSignal } = {},
): Promise<LoginResult> {
  const query = next ? `?next=${encodeURIComponent(next)}` : ''
  const response = await fetch(`/api/auth/login${query}`, {
    method: 'POST',
    credentials: 'same-origin',
    signal,
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(credentials),
  })
  if (!response.ok) throw await errorFromResponse(response, 'Sign in')
  return response.json() as Promise<LoginResult>
}

/** Register by a valid invite link or an allow-listed email address. */
export async function registerAccount(
  credentials: RegistrationCredentials,
  { inviteToken, signal }: { inviteToken?: string; signal?: AbortSignal } = {},
): Promise<RegistrationResult> {
  const query = inviteToken ? `?token=${encodeURIComponent(inviteToken)}` : ''
  const response = await fetch(`/api/auth/register${query}`, {
    method: 'POST',
    credentials: 'same-origin',
    signal,
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(credentials),
  })
  if (!response.ok) throw await errorFromResponse(response, 'Create account')
  return response.json() as Promise<RegistrationResult>
}

/** Request instructions; the response is identical for known and unknown email addresses. */
export async function requestPasswordReset(email: string): Promise<PasswordResetResult> {
  const response = await fetch('/api/auth/password-reset/request', {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ email }),
  })
  if (!response.ok) throw await errorFromResponse(response, 'Request password reset')
  return response.json() as Promise<PasswordResetResult>
}

/** Complete a reset using the opaque, short-lived token from the emailed link. */
export async function resetPassword(
  token: string,
  credentials: { password: string; confirm_password: string },
): Promise<PasswordResetResult> {
  const response = await fetch(`/api/auth/password-reset/${encodeURIComponent(token)}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(credentials),
  })
  if (!response.ok) throw await errorFromResponse(response, 'Reset password')
  return response.json() as Promise<PasswordResetResult>
}
