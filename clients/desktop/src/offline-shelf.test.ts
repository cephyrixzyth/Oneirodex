import { describe, expect, it } from 'vitest'

import {
  installedOfflineGames,
  loadOfflineInstalledShelf,
  OFFLINE_SHELF_STORAGE_KEY,
  saveOfflineInstalledShelf,
} from './offline-shelf.js'

function memoryStorage() {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  }
}

const identity = {
  serverUrl: 'https://household.example/',
  accountId: 'account-a',
  deviceId: 'device-a',
  token: 'same-high-entropy-token',
}

describe('offline Installed shelf', () => {
  it('loads only for the exact previously verified server, account, device and credential', async () => {
    const storage = memoryStorage()
    await saveOfflineInstalledShelf(identity, [
      { uuid: 'game-a', name: 'Game A', private_metadata: 'not persisted' },
      { uuid: 'game-b', name: 'Game B' },
    ], storage)

    expect(await loadOfflineInstalledShelf({ ...identity, accountId: undefined }, storage)).toEqual({
      accountId: 'account-a',
      games: [
        { uuid: 'game-a', name: 'Game A' },
        { uuid: 'game-b', name: 'Game B' },
      ],
    })
    expect(JSON.parse(storage.getItem(OFFLINE_SHELF_STORAGE_KEY) || '{}')).not.toHaveProperty(
      'token',
    )
    await expect(
      loadOfflineInstalledShelf({ ...identity, accountId: 'account-b' }, storage),
    ).resolves.toBeNull()
    await expect(
      loadOfflineInstalledShelf({ ...identity, deviceId: 'device-b' }, storage),
    ).resolves.toBeNull()
    await expect(
      loadOfflineInstalledShelf({ ...identity, serverUrl: 'https://other.example' }, storage),
    ).resolves.toBeNull()
    await expect(
      loadOfflineInstalledShelf({ ...identity, token: 'different-token' }, storage),
    ).resolves.toBeNull()
  })

  it('limits offline cards to cached games with both local install records and launchable state', () => {
    const games = [
      { uuid: 'installed', name: 'Installed' },
      { uuid: 'not-installed', name: 'Not installed' },
    ]
    expect(
      installedOfflineGames(games, { installed: { extractPath: 'local' } }, (uuid) =>
        uuid === 'installed',
      ),
    ).toEqual([{ uuid: 'installed', name: 'Installed' }])
  })
})
