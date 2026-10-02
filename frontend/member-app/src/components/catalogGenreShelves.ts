import { fetchBrowseGames } from '../api/browse'
import { fetchFilterOptions } from '../api/filters'

/**
 * Covers per genre shelf. A shelf is a sample you scroll, not the genre.
 *
 * 20 because `/browse_games` takes `per_page` from a fixed allowlist
 * (`utils/browse_pagination.py`: 20 / 50 / 100 / …) and clamps an off-list
 * value **down** to the nearest allowed size. Asking for 30 therefore served
 * 20 and made this constant a lie about what a shelf actually holds. Ask for
 * what you will be given.
 */
export const SHELF_SIZE = 20

/**
 * Filter keys a genre shelf inherits from the catalog bar.
 *
 * Deliberately a list rather than a spread of `filters`: `page`, `per_page`
 * and `sort` belong to the paged Tile view, and passing them through would
 * page a shelf — which is the bug this module exists to remove.
 */
const INHERITED_FILTER_KEYS = [
  'library_uuid',
  'library_platform',
  'igdb_platform',
  'item_kind',
  'name',
  'q',
  'theme',
  'game_mode',
  'player_perspective',
  'favorites',
  'signal',
  // LIB-02: without these the Grid view silently ignored store / ownership filters.
  'store',
  'store_match',
  'ownership',
]

export function shelfQuery(filters: any, genre: any) {
  const query: Record<string, any> = { genre, page: 1, per_page: SHELF_SIZE }
  for (const key of INHERITED_FILTER_KEYS) {
    const value = filters?.[key]
    if (value !== undefined && value !== null && value !== '') {
      query[key] = value
    }
  }
  return query
}

/**
 * Genre names for the shelves, in the order they should appear.
 *
 * `/api/filters/bundle` is the same list the Filters popover uses, so a genre
 * with nothing behind it never reaches the page and Grid cannot invent a shelf
 * the catalog cannot filter to.
 */
export async function fetchShelfGenres({ signal }: LooseProps = {}) {
  const options = await fetchFilterOptions({ signal })
  return (options.genres || [])
    .map((entry: any) => (typeof entry === 'string' ? entry : entry?.name))
    .filter((name: any) => typeof name === 'string' && name.trim() !== '')
}

export async function fetchShelfGames(filters: any, genre: any, { signal }: LooseProps = {}) {
  const payload = await fetchBrowseGames(shelfQuery(filters, genre), { signal })
  return {
    games: Array.isArray(payload?.games) ? payload.games : [],
    total: Number.isFinite(payload?.total) ? payload.total : 0,
  }
}
