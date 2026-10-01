import { getJson } from './client'

/** One option row as the bundle returns it; FilterBar reads fields by name. */
export type FilterOption = Record<string, unknown>

export interface FilterOptions {
  libraries: FilterOption[]
  libraryPlatforms: FilterOption[]
  igdbPlatforms: FilterOption[]
  genres: FilterOption[]
  themes: FilterOption[]
  gameModes: FilterOption[]
  playerPerspectives: FilterOption[]
  /** LIB-02: stores the browse filter can answer for (recorded ownership, policy on). */
  ownershipStores?: { id: string; name: string }[]
}

export async function fetchFilterOptions({ signal }: LooseProps = {}): Promise<FilterOptions> {
  const data = await getJson('/api/filters/bundle', { signal, label: '/api/filters/bundle' })
  return {
    libraries: Array.isArray(data.libraries) ? data.libraries : [],
    libraryPlatforms: Array.isArray(data.libraryPlatforms) ? data.libraryPlatforms : [],
    igdbPlatforms: Array.isArray(data.igdbPlatforms) ? data.igdbPlatforms : [],
    genres: Array.isArray(data.genres) ? data.genres : [],
    themes: Array.isArray(data.themes) ? data.themes : [],
    gameModes: Array.isArray(data.gameModes) ? data.gameModes : [],
    playerPerspectives: Array.isArray(data.playerPerspectives) ? data.playerPerspectives : [],
    ownershipStores: Array.isArray(data.ownershipStores) ? data.ownershipStores : [],
  }
}
