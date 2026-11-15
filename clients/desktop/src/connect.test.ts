import { describe, expect, it, vi } from 'vitest'
import { OneirodexApiError } from '@oneirodex/api-client'
import type { OneirodexClient } from '@oneirodex/api-client'

import {
  fetchLibraryPreview,
  formatDesktopApiError,
  formatKeychainError,
  mergeUpdateSignalsFromLibrary,
  shapeInvalidConnectionResult,
  validateConnection,
} from './connect.js'
import { createLifecycleRegistry } from './lifecycle.js'
import { createAuthStore } from './auth.js'
import { createDesktopApi } from './api.js'

function mockClient(partial: Partial<OneirodexClient>): OneirodexClient {
  return partial as OneirodexClient
}

describe('validateConnection', () => {
  it('succeeds when collections endpoint returns data', async () => {
    const client = mockClient({
      browse: {
        listCollections: vi.fn(async () => [{ id: 1, name: 'Main' }]),
        search: vi.fn(),
      },
    })

    const result = await validateConnection(client)
    expect(result).toEqual({ ok: true, collectionCount: 1 })
  })

  it('returns error message when API call fails', async () => {
    const client = mockClient({
      browse: {
        listCollections: vi.fn(async () => {
          throw new Error('Unauthorized')
        }),
        search: vi.fn(),
      },
    })

    const result = await validateConnection(client)
    expect(result).toEqual({ ok: false, message: 'Unauthorized', cause: 'unknown' })
  })

  it('maps 401 to full-secret / hyphen guidance', async () => {
    const client = mockClient({
      browse: {
        listCollections: vi.fn(async () => {
          throw new OneirodexApiError(401, { error: 'unauthorized' })
        }),
        search: vi.fn(),
      },
    })

    const result = await validateConnection(client)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.cause).toBe('unauthorized')
      expect(result.message).toMatch(/full one-time secret/i)
      expect(result.message).toMatch(/hyphen/i)
    }
  })

  it('maps network failures distinctly from 401', async () => {
    const client = mockClient({
      browse: {
        listCollections: vi.fn(async () => {
          throw new TypeError('Failed to fetch')
        }),
        search: vi.fn(),
      },
    })

    const result = await validateConnection(client)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.cause).toBe('network')
      expect(result.message).toMatch(/Network\/TLS\/CORS/i)
    }
  })

  it('maps opaque failed-to-load style errors as network', async () => {
    const client = mockClient({
      browse: {
        listCollections: vi.fn(async () => {
          throw new TypeError('Failed to load')
        }),
        search: vi.fn(),
      },
    })

    const result = await validateConnection(client)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.cause).toBe('network')
      expect(result.message).toMatch(/Network\/TLS\/CORS/i)
    }
  })

  it('maps 403 API errors to scope guidance', async () => {
    const client = mockClient({
      browse: {
        listCollections: vi.fn(async () => {
          throw new OneirodexApiError(403, { error: 'forbidden' })
        }),
        search: vi.fn(),
      },
    })

    const result = await validateConnection(client)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.cause).toBe('forbidden')
      expect(result.message).toContain('403')
      expect(result.message).toContain('read:library')
    }
  })
})

describe('formatDesktopApiError', () => {
  it('maps permission-style Tauri errors', () => {
    expect(formatDesktopApiError(new Error('Command append_file_bytes not allowed'))).toContain(
      'Companion permission error',
    )
  })

  it('maps keyring Bad data to credential-store copy', () => {
    expect(formatKeychainError(new Error('Bad data'))).toMatch(/credential store/i)
    expect(formatDesktopApiError(new Error('Bad data'))).toMatch(/credential store/i)
  })
})

describe('shapeInvalidConnectionResult', () => {
  it('explains paste noise and hyphen safety', () => {
    const result = shapeInvalidConnectionResult()
    expect(result.cause).toBe('shape_invalid')
    expect(result.message).toMatch(/gt_<prefix>_<urlsafe-secret>/)
    expect(result.message).toMatch(/hyphen/i)
  })
})

describe('fetchLibraryPreview', () => {
  it('accepts the real search endpoint array and follows empty-query fallbacks', async () => {
    const queries: string[] = []
    const api = createDesktopApi(
      createAuthStore({ baseUrl: 'https://fixture.example', token: 'gt_abcd1234_synthetic' }),
      async (input) => {
        const query = new URL(String(input)).searchParams.get('query') ?? ''
        queries.push(query)
        return Response.json(query === 'a' ? [{ uuid: 'game-a', name: 'Shared game' }] : [])
      },
    )
    await expect(fetchLibraryPreview(api, 12, true)).resolves.toEqual([
      { uuid: 'game-a', name: 'Shared game' },
    ])
    expect(queries).toEqual(['', '*', 'a'])
  })

  it.each([null, {}, { results: 'invalid' }])(
    'rejects malformed strict search response %j as protocol failure',
    async (body) => {
      const api = createDesktopApi(
        createAuthStore({ baseUrl: 'https://fixture.example', token: 'gt_abcd1234_synthetic' }),
        async () => Response.json(body),
      )
      await expect(fetchLibraryPreview(api, 12, true)).rejects.toMatchObject({ cause: 'protocol' })
    },
  )
  it('returns search results from games array', async () => {
    const client = mockClient({
      browse: {
        listCollections: vi.fn(),
        search: vi.fn(async () => ({
          games: [
            { uuid: 'game-1', name: 'Doom' },
            { uuid: 'game-2', name: 'Quake' },
          ],
        })),
      },
    })

    const games = await fetchLibraryPreview(client, 5)
    expect(games).toHaveLength(2)
    expect(games[0]?.name).toBe('Doom')
  })
})

describe('mergeUpdateSignalsFromLibrary', () => {
  it('signals update_available for installed games flagged by search', () => {
    const registry = createLifecycleRegistry()
    registry.apply('a', 'download')
    registry.apply('a', 'install')
    registry.apply('b', 'download')
    registry.apply('b', 'install')

    const n = mergeUpdateSignalsFromLibrary(registry, [
      { uuid: 'a', name: 'A', has_updates: true },
      { uuid: 'b', name: 'B', lifecycle_state: 'update_available' },
      { uuid: 'c', name: 'C', has_updates: true },
    ])

    expect(n).toBe(2)
    expect(registry.get('a')).toBe('update_available')
    expect(registry.get('b')).toBe('update_available')
    expect(registry.get('c')).toBe('not_downloaded')
  })
})
