import { getJson } from './client'

function requireJson(data: any, label: string) {
  if (data === undefined) {
    throw new Error(`${label} returned non-JSON (session expired or server error)`)
  }
  return data
}

export async function fetchDiscoverSections({ signal }: LooseProps = {}) {
  const data = requireJson(
    await getJson('/api/discover/sections', { signal, label: 'discover sections' }),
    'discover sections',
  )
  const sections = Array.isArray(data.sections) ? data.sections : []
  // The token names this feed's dedupe record. Rows hand it back when they page
  // so their later tiles skip what the rows above already showed.
  const feedToken = data.feed_token || ''
  if (feedToken) {
    for (const section of sections) {
      section.feed_token = feedToken
    }
  }
  // The zone strip rides along with the feed. It is derived server-side from
  // these very sections, so it can never offer a zone the page did not render.
  return { sections, zones: Array.isArray(data.zones) ? data.zones : [] }
}

/**
 * One row's games, windowed.
 *
 * Backs both halves of a deep row: the shelf asking for the tiles past its
 * first window, and the row page paging through the whole thing.
 */
export async function fetchDiscoverRow(
  identifier: any,
  { offset = 0, limit, feedToken, signal }: LooseProps = {},
) {
  const params = new URLSearchParams({ offset: String(offset) })
  if (limit) {
    params.set('limit', String(limit))
  }
  if (feedToken) {
    params.set('feed_token', feedToken)
  }
  const data = requireJson(
    await getJson(`/api/discover/rows/${encodeURIComponent(identifier)}?${params}`, {
      signal,
      label: 'discover row',
    }),
    'discover row',
  )
  return {
    identifier: data.identifier || identifier,
    title: data.title || '',
    itemKind: data.item_kind || 'games',
    offset: Number(data.offset) || 0,
    limit: Number(data.limit) || 0,
    // Game rows answer with `games`, other kinds with `items`. Normalised to
    // one name here so callers do not repeat the branch.
    items: Array.isArray(data.games) ? data.games : Array.isArray(data.items) ? data.items : [],
    hasMore: Boolean(data.has_more),
    // How many the row holds altogether, or null when the server counted to its
    // probe ceiling without reaching the end. `null` is not 0 and must not
    // collapse to it — a caller that cannot say how many are left should say
    // nothing, not "0 more".
    total: Number.isFinite(data.total) ? Number(data.total) : null,
    totalIsEstimate: Boolean(data.total_is_estimate),
    moreHref: data.more_href || '',
  }
}

/**
 * One zone: the feed narrowed to the rows that belong to that surface.
 */
export async function fetchDiscoverZone(slug: any, { signal }: LooseProps = {}) {
  const data = requireJson(
    await getJson(`/api/discover/zones/${encodeURIComponent(slug)}`, {
      signal,
      label: 'discover zone',
    }),
    'discover zone',
  )
  const sections = Array.isArray(data.sections) ? data.sections : []
  // Same dedupe contract as the main feed: rows page against the token this
  // assembly produced, not the one the main feed produced.
  const feedToken = data.feed_token || ''
  if (feedToken) {
    for (const section of sections) {
      section.feed_token = feedToken
    }
  }
  return {
    slug: data.slug || slug,
    title: data.title || 'Discover',
    lede: data.lede || '',
    sections,
  }
}

/**
 * Virtual Discover shelves for one genre (unplayed / newest / loved).
 */
export async function fetchGenreHub(genre: any, { signal }: LooseProps = {}) {
  const data = requireJson(
    await getJson(`/api/discover/hubs/genre/${encodeURIComponent(genre)}`, {
      signal,
      label: 'genre hub',
    }),
    'genre hub',
  )
  return {
    genre: data.genre || genre,
    title: data.title || data.genre || 'Genre',
    catalogHref: data.catalog_href || '',
    sections: Array.isArray(data.sections) ? data.sections : [],
  }
}

export interface SurpriseGenre {
  id: number
  name: string
}

export interface SurprisePick {
  game: Record<string, unknown> | null
  reason: string
  genre: SurpriseGenre | null
  genres: SurpriseGenre[]
}

/**
 * One title from the top of this member's ranking (INSP-4b), plus the genres
 * the picker offers. `exclude` is what was just shown, so "another" moves on.
 */
export async function fetchSurprise({
  genre = null,
  exclude = [],
  signal,
}: {
  genre?: number | null
  exclude?: string[]
  signal?: AbortSignal
} = {}): Promise<SurprisePick> {
  const params = new URLSearchParams()
  if (genre != null) params.set('genre', String(genre))
  if (exclude.length) params.set('exclude', exclude.join(','))
  const query = params.toString()
  const data = requireJson(
    await getJson(`/api/discover/surprise${query ? `?${query}` : ''}`, {
      signal,
      label: 'surprise',
    }),
    'surprise',
  )
  return {
    game: data.game || null,
    reason: String(data.reason || ''),
    genre: data.genre || null,
    genres: Array.isArray(data.genres) ? data.genres : [],
  }
}
