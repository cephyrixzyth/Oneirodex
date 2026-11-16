import { describe, expect, it } from 'vitest'

import { harness, okEnvelope } from './test-harness.js'

describe('device identity API', () => {
  it('reads the stable account ID through the scoped native identity route', async () => {
    const { calls, client } = harness(200, okEnvelope({ account_id: 'account-uuid' }))
    await expect(client.device.identity()).resolves.toMatchObject({ account_id: 'account-uuid' })
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('https://host.example/api/client/identity')
    expect(calls[0].method).toBe('GET')
    expect(calls[0].headers.get('authorization')).toBe('Bearer gt_ab12_secret')
  })
})
