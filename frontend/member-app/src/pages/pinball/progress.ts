import { csrfHeaders } from '@oneirodex/ui'
import { memberResource, withMemberError } from '../../api/client'
import { requirePrivateVrControl } from '../../api/vr'
import { validateMoonfall } from './model'
import type { MoonfallState } from './model'

const path = '/api/room-games/moonfall-pinball/progress'
const transport = memberResource((request) => ({
  read: (signal?: AbortSignal) => request<unknown>(path, { signal, cache: 'no-store' }),
  mutate: (method: 'PUT' | 'DELETE', body: unknown, signal?: AbortSignal) =>
    request<unknown>(path, {
      method,
      signal,
      cache: 'no-store',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    }),
}))

export interface SavedMoonfall {
  game_id: 'moonfall-pinball'
  revision: number
  state: MoonfallState | null
  updated_at: string | null
}
function invalid(): never {
  throw new Error('Saved game progress could not be read. Your run was not changed.')
}
function revision(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > 2_000_000_000)
    return invalid()
  return value
}
function read(value: unknown): SavedMoonfall {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid()
  const body = value as Record<string, unknown>
  if (body.game_id !== 'moonfall-pinball') return invalid()
  if (
    body.updated_at !== null &&
    (typeof body.updated_at !== 'string' || !Number.isFinite(Date.parse(body.updated_at)))
  )
    return invalid()
  return {
    game_id: 'moonfall-pinball',
    revision: revision(body.revision),
    state: body.state === null ? null : validateMoonfall(body.state),
    updated_at: body.updated_at as string | null,
  }
}

export async function loadMoonfallProgress(signal?: AbortSignal): Promise<SavedMoonfall> {
  await requirePrivateVrControl(signal)
  return read(await withMemberError(transport.read(signal), 'Could not load game progress'))
}

export async function saveMoonfallProgress(
  expected: number,
  value: unknown,
  signal?: AbortSignal,
): Promise<SavedMoonfall> {
  const state = validateMoonfall(value)
  revision(expected)
  await requirePrivateVrControl(signal)
  const result = read(
    await withMemberError(
      transport.mutate('PUT', { revision: expected, state }, signal),
      'Could not save game progress',
    ),
  )
  if (result.revision !== expected + 1 || result.state === null) return invalid()
  return result
}

export async function resetMoonfallProgress(
  expected: number,
  signal?: AbortSignal,
): Promise<SavedMoonfall> {
  revision(expected)
  await requirePrivateVrControl(signal)
  const result = read(
    await withMemberError(
      transport.mutate('DELETE', { revision: expected }, signal),
      'Could not reset game progress',
    ),
  )
  if (result.state !== null || result.revision !== (expected === 0 ? 0 : expected + 1))
    return invalid()
  return result
}
