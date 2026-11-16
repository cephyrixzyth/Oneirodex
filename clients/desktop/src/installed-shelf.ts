import {
  OneirodexApiError,
  type OneirodexClient,
  type SearchResultItem,
} from '@oneirodex/api-client'
import { DesktopTransportError } from './api.js'
import type { GameInstallRecord } from './install-store.js'
import { MAX_OFFLINE_SHELF_GAMES } from './offline-shelf.js'

/** Verify only local installed IDs; the remote twelve-title preview is not an installed inventory. */
export async function readInstalledShelf(
  api: OneirodexClient,
  installs: Record<string, GameInstallRecord>,
  canLaunch: (uuid: string) => boolean,
  preview: SearchResultItem[],
  current: () => boolean,
): Promise<SearchResultItem[]> {
  const ids = Object.keys(installs).filter(
    (uuid) => !installs[uuid].pendingUninstall && canLaunch(uuid),
  )
  if (ids.length > MAX_OFFLINE_SHELF_GAMES) {
    throw new Error(
      'Installed shelf exceeds the 5,000-title cache capacity. Previous cached titles and game files are preserved.',
    )
  }
  const known = new Map(preview.map((game) => [game.uuid, game]))
  const verified = new Map<string, SearchResultItem>()
  const controller = new AbortController()
  let next = 0
  const checkCurrent = () => {
    if (!current() || controller.signal.aborted)
      throw new DOMException('Connection changed', 'AbortError')
  }
  async function worker(): Promise<void> {
    while (next < ids.length) {
      checkCurrent()
      const uuid = ids[next++]
      let game: SearchResultItem | undefined = known.get(uuid)
      if (!game) {
        try {
          const details = await api.game.details(uuid, controller.signal)
          checkCurrent()
          if (
            details?.uuid !== uuid ||
            typeof details.name !== 'string' ||
            !details.name.trim() ||
            details.name.trim().length > 300
          ) {
            throw new DesktopTransportError('protocol')
          }
          game = { uuid, name: details.name.trim() }
        } catch (error) {
          if (error instanceof OneirodexApiError && [403, 404].includes(error.status)) continue
          throw error
        }
      }
      checkCurrent()
      if (
        !uuid ||
        uuid.length > 128 ||
        typeof game.name !== 'string' ||
        !game.name.trim() ||
        game.name.trim().length > 300
      ) {
        throw new DesktopTransportError('protocol')
      }
      verified.set(uuid, game)
    }
  }
  try {
    checkCurrent()
    await Promise.all(Array.from({ length: Math.min(4, ids.length) }, worker))
    checkCurrent()
    return ids.flatMap((uuid) => (verified.has(uuid) ? [verified.get(uuid)!] : []))
  } finally {
    controller.abort()
  }
}
