import { csrfHeaders } from './csrf.js'
import { errorFromResponse } from './envelopeError.js'

export interface AccountLoginSession {
  id: string
  current: boolean
  created_at: string
  last_seen_at: string
  expires_at: string
}

export interface ListAccountLoginSessionsResponse {
  sessions: AccountLoginSession[]
}

export async function listAccountLoginSessions({
  signal,
}: { signal?: AbortSignal } = {}): Promise<ListAccountLoginSessionsResponse> {
  const response = await fetch('/api/account/sessions', {
    credentials: 'same-origin',
    signal,
  })
  if (!response.ok) {
    throw await errorFromResponse(response, 'List sessions')
  }
  return response.json() as Promise<ListAccountLoginSessionsResponse>
}

export async function revokeAccountLoginSession(sessionId: string): Promise<unknown> {
  const response = await fetch(`/api/account/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
    credentials: 'same-origin',
    headers: csrfHeaders(),
  })
  if (!response.ok) {
    throw await errorFromResponse(response, 'Revoke session')
  }
  return response.json()
}

export async function revokeAllAccountLoginSessions(): Promise<unknown> {
  const response = await fetch('/api/account/sessions', {
    method: 'DELETE',
    credentials: 'same-origin',
    headers: csrfHeaders(),
  })
  if (!response.ok) {
    throw await errorFromResponse(response, 'Revoke all sessions')
  }
  return response.json()
}
