import { describe, expect, it, vi } from 'vitest'

import { fetchAssistPack } from './assists.js'

describe('fetchAssistPack', () => {
  it('refuses redirects for bearer-authenticated API reads', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ enabled: true, pack: { game_uuid: 'g1', title: 'Assist', policy: 'safe', toggles: [] } }),
    })) as unknown as typeof fetch

    const result = await fetchAssistPack(
      { getBaseUrl: () => 'https://server.example', getToken: () => 'gt_secret' } as never,
      'g1',
      { fetchImpl },
    )

    expect(result?.title).toBe('Assist')
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://server.example/api/games/g1/assists',
      expect.objectContaining({ redirect: 'error' }),
    )
  })
})
