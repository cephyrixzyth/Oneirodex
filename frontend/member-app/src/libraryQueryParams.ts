import { BADGE_FILTER_PARAMS, badgeFiltersFromSearchParams } from './components/BadgeFilterChips'
import { itemKindFromSearchParams } from './components/ItemKindFilterChips'

/** Every filter the catalog reads from the URL.
 *
 * Values are optional because the chip helpers spread in a key only when the
 * param is present, and `cleanFilters` strips the empties before they reach
 * the browse request anyway. */
export type LibraryFilters = Record<string, string | undefined>

/**
 * URL query params -> the library's filter object, and back again.
 *
 * Lifted out of `LibraryApp` when adding `filter_tree` (INSP-29) pushed that
 * file past the 600-line component ratchet. They are pure functions over
 * `URLSearchParams` with no React in them, so they belong beside the chips
 * they compose rather than inside a page component.
 *
 * Both are **allow-lists**, which is the thing to remember when adding a
 * param: one missing from them is not an error anywhere -- the page simply
 * opens unfiltered, which reads as "the filter matched everything" rather
 * than as a bug.
 */

export function filtersFromSearchParams(searchParams: URLSearchParams): LibraryFilters {
  const next: LibraryFilters = {
    ...badgeFiltersFromSearchParams(searchParams),
    ...itemKindFromSearchParams(searchParams),
  }
  const libraryPlatform = searchParams.get('library_platform')
  if (libraryPlatform) {
    next.library_platform = libraryPlatform
  }
  const playMode = searchParams.get('play_mode')
  if (playMode) {
    next.play_mode = playMode
  }
  const genre = searchParams.get('genre')
  if (genre) {
    next.genre = genre
  }
  const theme = searchParams.get('theme')
  if (theme) {
    next.theme = theme
  }
  const gameMode = searchParams.get('game_mode')
  if (gameMode) {
    next.game_mode = gameMode
  }
  const perspective = searchParams.get('player_perspective')
  if (perspective) {
    next.player_perspective = perspective
  }
  const name = (searchParams.get('name') || searchParams.get('q') || '').trim()
  if (name) {
    next.name = name
  }
  // INSP-29: a smart collection is a saved filter opened as a link, so the
  // tree has to survive the URL. Passed through verbatim -- the server is the
  // one that validates it, and a tree it refuses comes back as a 400 naming
  // the offending part rather than being quietly ignored here.
  const filterTree = (searchParams.get('filter_tree') || '').trim()
  if (filterTree) {
    next.filter_tree = filterTree
  }
  // LIB-02: store / ownership filters live in the URL, so a filtered view can
  // be linked and survives a reload. `store` may repeat or be a comma list.
  const stores = searchParams
    .getAll('store')
    .flatMap((value) => value.split(','))
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean)
  if (stores.length) {
    next.store = Array.from(new Set(stores)).join(',')
  }
  const storeMatch = (searchParams.get('store_match') || '').trim().toLowerCase()
  if (storeMatch) {
    next.store_match = storeMatch
  }
  const ownership = (searchParams.get('ownership') || '').trim().toLowerCase()
  if (ownership) {
    next.ownership = ownership
  }
  return next
}

/** Ownership filters mirrored into the URL (the rest persist in the cookie, as before). */
export const OWNERSHIP_FILTER_KEYS = ['store', 'store_match', 'ownership'] as const

/** Library filter params a URL may carry, with the older alias each one also answers to. */
const URL_FILTER_PARAMS: [key: string, alias?: string][] = [
  ['library_platform'],
  ['play_mode'],
  ['genre'],
  ['theme'],
  ['game_mode'],
  ['player_perspective'],
  ['item_kind', 'content_kind'],
  ['name', 'q'],
  ['filter_tree'],
  ...BADGE_FILTER_PARAMS.map((param): [string] => [param]),
]

/**
 * The URL to show for `filters`. Ownership params are always written, so a
 * store-filtered view can be linked. Any other filter param the URL already
 * carries (a deep link's genre, a Systems page's platform, a smart collection's
 * tree) is updated to the applied value or dropped. Otherwise the URL would
 * still hold the old value, and the next URL read would put it back.
 * Filters the URL never carried are not added: those persist in the cookie.
 */
export function withLibraryParams(
  current: URLSearchParams,
  filters: LibraryFilters,
): URLSearchParams {
  const next = new URLSearchParams(current)
  for (const key of OWNERSHIP_FILTER_KEYS) {
    const value = filters[key]
    if (value) next.set(key, value)
    else next.delete(key)
  }
  for (const [key, alias] of URL_FILTER_PARAMS) {
    if (!next.has(key) && !(alias && next.has(alias))) continue
    const value = filters[key]
    if (alias) next.delete(alias)
    if (value) next.set(key, value)
    else next.delete(key)
  }
  return next
}

export function searchParamsHaveLibraryFilters(searchParams: URLSearchParams): boolean {
  if (
    searchParams.has('library_platform') ||
    searchParams.has('play_mode') ||
    searchParams.has('genre') ||
    searchParams.has('theme') ||
    searchParams.has('game_mode') ||
    searchParams.has('player_perspective') ||
    searchParams.has('item_kind') ||
    searchParams.has('content_kind') ||
    searchParams.has('name') ||
    searchParams.has('q') ||
    searchParams.has('filter_tree') ||
    searchParams.has('store') ||
    searchParams.has('store_match') ||
    searchParams.has('ownership')
  ) {
    return true
  }
  return BADGE_FILTER_PARAMS.some((param) => searchParams.has(param))
}
