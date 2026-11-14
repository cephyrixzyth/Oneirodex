import { describe, expect, it } from 'vitest'
import { launchProfileBinding } from './launch-profile.js'

const profile = {
  serverUrl: 'https://household.example/',
  accountId: 'verified-account',
  deviceId: 'verified-device',
  token: 'synthetic-high-entropy-credential',
}

describe('verified native launch profile binding', () => {
  it('matches the existing offline shelf URL normalization and reveals no identity values', async () => {
    const binding = await launchProfileBinding(profile)
    expect(binding).toMatch(/^[a-f0-9]{64}$/)
    expect(
      await launchProfileBinding({ ...profile, serverUrl: ' https://household.example/// ' }),
    ).toBe(binding)
    expect(JSON.stringify({ binding })).not.toContain(profile.token)
    expect(JSON.stringify({ binding })).not.toContain(profile.accountId)
  })
  it.each(['serverUrl', 'accountId', 'deviceId', 'token'] as const)(
    'separates a changed %s',
    async (field) => {
      const original = await launchProfileBinding(profile)
      expect(
        await launchProfileBinding({ ...profile, [field]: `other-${profile[field]}` }),
      ).not.toBe(original)
    },
  )
  it.each(['serverUrl', 'accountId', 'deviceId', 'token'] as const)(
    'rejects missing %s',
    async (field) => {
      expect(await launchProfileBinding({ ...profile, [field]: '' })).toBeNull()
    },
  )
})
