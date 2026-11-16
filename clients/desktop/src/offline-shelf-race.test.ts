import { webcrypto } from 'node:crypto'
import { afterEach, expect, it, vi } from 'vitest'
import { OFFLINE_SHELF_STORAGE_KEY, saveOfflineInstalledShelf } from './offline-shelf.js'
afterEach(() => vi.unstubAllGlobals())
it('does not publish an obsolete account snapshot after async hashing completes', async () => {
  let finish!: (value: ArrayBuffer) => void
  const delayed = new Promise<ArrayBuffer>((resolve) => {
    finish = resolve
  })
  vi.stubGlobal('crypto', { subtle: { digest: () => delayed } })
  const saved = new Map([[OFFLINE_SHELF_STORAGE_KEY, 'newer-account-snapshot']])
  let current = true
  const pending = saveOfflineInstalledShelf(
    { serverUrl: 'https://a.example', accountId: 'a', deviceId: 'device', token: 'fixture' },
    [{ uuid: 'a', name: 'Old title' }],
    { setItem: (key, value) => saved.set(key, value) },
    () => current,
  )
  current = false
  finish(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode('fixture')))
  await pending
  expect(saved.get(OFFLINE_SHELF_STORAGE_KEY)).toBe('newer-account-snapshot')
})
