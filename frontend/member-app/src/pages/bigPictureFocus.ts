import { fetchGameDetails } from '../api/gameDetails'

function focusGameFromQuery() {
  try {
    return new URLSearchParams(window.location.search).get('game') || ''
  } catch {
    return ''
  }
}

/**
 * Index of the game named by `?game=` in the first page, fetching and
 * prepending it when it is not on that page. -1 when no game is requested;
 * throws when the requested game is unavailable.
 */
export async function placeFocusedGame(
  list: Array<{ uuid?: unknown }>,
  signal: AbortSignal,
): Promise<number> {
  const wanted = focusGameFromQuery()
  if (!wanted) return -1
  const found = list.findIndex((game) => game.uuid === wanted)
  if (found >= 0) return found
  const target = await fetchGameDetails(wanted, { signal })
  if (target.uuid !== wanted) throw new Error('Game unavailable')
  list.unshift(target)
  return 0
}
