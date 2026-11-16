import type { SearchResultItem } from '@oneirodex/api-client'

const STORAGE_KEY = 'oneirodex-offline-installed-shelf-v1'
export const MAX_OFFLINE_SHELF_GAMES = 5_000

export interface OfflineShelfIdentity {
  serverUrl: string
  accountId?: string
  deviceId: string
  token: string
}

export interface OfflineShelfGame {
  uuid: string
  name: string
}

interface StoredOfflineShelf {
  version: 1
  serverUrl: string
  accountId: string
  deviceId: string
  credentialFingerprint: string
  games: OfflineShelfGame[]
}

export function normalizeServerUrl(value: string): string {
  return value.trim().replace(/\/+$/, '')
}

export async function sha256Fingerprint(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function normalizeGames(games: SearchResultItem[]): OfflineShelfGame[] {
  const unique = new Map<string, OfflineShelfGame>()
  for (const game of games) {
    const uuid = typeof game?.uuid === 'string' ? game.uuid.trim() : ''
    const name = typeof game?.name === 'string' ? game.name.trim() : ''
    if (!uuid || uuid.length > 128 || !name || name.length > 300 || unique.has(uuid)) {
      continue
    }
    unique.set(uuid, { uuid, name })
    if (unique.size >= MAX_OFFLINE_SHELF_GAMES) break
  }
  return [...unique.values()]
}

export async function saveOfflineInstalledShelf(
  identity: OfflineShelfIdentity,
  games: SearchResultItem[],
  storage: Pick<Storage, 'setItem'> = localStorage,
  canCommit: () => boolean = () => true,
): Promise<void> {
  const serverUrl = normalizeServerUrl(identity.serverUrl)
  if (!serverUrl || !identity.accountId || !identity.deviceId || !identity.token) {
    throw new Error('Verified offline shelf identity is incomplete')
  }
  const record: StoredOfflineShelf = {
    version: 1,
    serverUrl,
    accountId: identity.accountId,
    deviceId: identity.deviceId,
    credentialFingerprint: await sha256Fingerprint(identity.token),
    games: normalizeGames(games),
  }
  if (canCommit()) storage.setItem(STORAGE_KEY, JSON.stringify(record))
}

export async function loadOfflineInstalledShelf(
  identity: OfflineShelfIdentity,
  storage: Pick<Storage, 'getItem'> = localStorage,
): Promise<{ accountId: string; games: OfflineShelfGame[] } | null> {
  const raw = storage.getItem(STORAGE_KEY)
  if (!raw || !identity.token) return null

  let saved: StoredOfflineShelf
  try {
    saved = JSON.parse(raw) as StoredOfflineShelf
  } catch {
    return null
  }

  if (
    saved.version !== 1 ||
    saved.serverUrl !== normalizeServerUrl(identity.serverUrl) ||
    (identity.accountId && saved.accountId !== identity.accountId) ||
    saved.deviceId !== identity.deviceId ||
    saved.credentialFingerprint !== (await sha256Fingerprint(identity.token)) ||
    !Array.isArray(saved.games)
  ) {
    return null
  }
  return { accountId: saved.accountId, games: normalizeGames(saved.games as SearchResultItem[]) }
}

export function installedOfflineGames<T extends OfflineShelfGame>(
  games: T[],
  localInstalls: Record<string, unknown>,
  stateCanLaunch: (uuid: string) => boolean,
): T[] {
  return games.filter((game) => Boolean(localInstalls[game.uuid]) && stateCanLaunch(game.uuid))
}

export const OFFLINE_SHELF_STORAGE_KEY = STORAGE_KEY

/** Removes local catalog metadata only, never installs or saves. */
export function clearOfflineInstalledShelf(
  storage: Pick<Storage, 'removeItem'> = localStorage,
): void {
  storage.removeItem(STORAGE_KEY)
}
