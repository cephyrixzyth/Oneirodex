import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createPersistedLifecycleRegistry,
  syncLifecycleRegistryToServer,
} from './lifecycle-store.js'
import { createLifecycleRegistry } from './lifecycle.js'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

describe('lifecycle persistence helpers', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('persists registry changes through onChange hook', async () => {
    const persisted: Array<{ gameUuid: string; state: string }> = []
    const registry = createPersistedLifecycleRegistry({
      persist: async (records) => {
        persisted.push(...records)
      },
    })

    registry.apply('game-1', 'download')
    registry.apply('game-1', 'install')

    expect(persisted.at(-1)).toEqual({ gameUuid: 'game-1', state: 'installed' })
  })

  it('hydrates initial records into registry', () => {
    const registry = createLifecycleRegistry({
      initial: [{ gameUuid: 'game-9', state: 'update_available' }],
    })

    expect(registry.get('game-9')).toBe('update_available')
  })

  it('refuses redirects when syncing bearer-authenticated lifecycle state', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, status: 200 })) as unknown as typeof fetch
    await syncLifecycleRegistryToServer(
      { getBaseUrl: () => 'https://server.example', getToken: () => 'gt_secret' } as never,
      [],
      fetchImpl,
    )

    expect(fetchImpl).toHaveBeenCalledWith(
      'https://server.example/api/client/lifecycle',
      expect.objectContaining({ redirect: 'error' }),
    )
  })
})
