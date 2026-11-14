/**
 * Normalize video URL lists from details payloads (CSV string, list, or embeds).
 * @param {unknown} raw
 * @returns {string[]}
 */
export function parseVideoUrls(raw: any) {
  if (raw == null || raw === '') return []
  if (Array.isArray(raw)) {
    return raw.map((u) => String(u).trim()).filter(Boolean)
  }
  if (typeof raw === 'string') {
    return raw
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
  }
  return []
}

/**
 * @param {string} url
 * @returns {string | null} YouTube embed URL
 */
export function youtubeEmbed(url: any) {
  if (!url || typeof url !== 'string') return null
  const embedMatch = url.match(/youtube\.com\/embed\/([\w-]{6,})/i)
  if (embedMatch) {
    return `https://www.youtube.com/embed/${embedMatch[1]}`
  }
  const match = url.match(/(?:youtu\.be\/|v=)([\w-]{6,})/i)
  return match ? `https://www.youtube.com/embed/${match[1]}` : null
}

/**
 * @param {string} url
 * @returns {boolean}
 */
export function isDirectVideoUrl(url: any) {
  if (!url || typeof url !== 'string') return false
  const path = url.split('?')[0].toLowerCase()
  return /\.(mp4|webm|ogv|ogg)$/.test(path)
}

/**
 * Mute + autoplay query params for a YouTube embed. Direct files are unchanged.
 * Never sets volume or unmute — hover trailers have no user-gesture audio.
 * @param {string} url
 * @returns {string | null}
 */
export function mutedHoverTrailerSrc(url: any) {
  if (!url || typeof url !== 'string') return null
  const trimmed = url.trim()
  if (!trimmed) return null
  if (isDirectVideoUrl(trimmed)) return trimmed
  const embed = youtubeEmbed(trimmed)
  if (!embed) return null
  try {
    const parsed = new URL(embed)
    parsed.searchParams.set('autoplay', '1')
    parsed.searchParams.set('mute', '1')
    parsed.searchParams.set('controls', '0')
    parsed.searchParams.set('playsinline', '1')
    parsed.searchParams.set('rel', '0')
    parsed.searchParams.set('modestbranding', '1')
    const videoId = parsed.pathname.split('/').filter(Boolean).pop()
    if (videoId) {
      parsed.searchParams.set('loop', '1')
      parsed.searchParams.set('playlist', videoId)
    }
    return parsed.toString()
  } catch {
    return null
  }
}

/**
 * @returns {boolean}
 */
export function prefersReducedMotion() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Prefer structured `game.trailers[].embed_url` (and has_trailers) before video_urls CSV/list.
 * @param {object} game
 * @returns {string[]} Embeddable iframe src URLs
 */
export function trailerEmbedUrls(game: any) {
  if (!game) return []

  const structured = Array.isArray(game.trailers) ? game.trailers : []
  if (structured.length > 0 || game.has_trailers === true) {
    const fromTrailers = structured
      .map((row: any) => {
        if (!row || typeof row !== 'object') {
          return youtubeEmbed(String(row || ''))
        }
        const embed = row.embed_url || row.url
        return youtubeEmbed(String(embed || '')) || (embed ? String(embed).trim() : null)
      })
      .filter(Boolean)
    if (fromTrailers.length) return fromTrailers
  }

  return parseVideoUrls(game.video_urls).map(youtubeEmbed).filter(Boolean)
}

/**
 * Prefer Backend youtube_demo_url / demo_url / youtube mark when no embeddable trailers exist.
 * @param {object} game
 * @returns {{ href: string, label: string } | null}
 */
function safeYouTubeUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const raw = value.trim()
  // eslint-disable-next-line no-control-regex -- Reject control bytes before URL parsing can normalize them.
  if (!raw || raw.length > 2048 || /[\u0000-\u001f\u007f]/.test(raw)) return null
  try {
    const url = new URL(raw)
    const host = url.hostname.toLowerCase()
    const isYouTubeHost =
      host === 'youtu.be' || host === 'youtube.com' || host.endsWith('.youtube.com')
    if (
      (url.protocol !== 'http:' && url.protocol !== 'https:') ||
      url.username ||
      url.password ||
      !isYouTubeHost
    ) {
      return null
    }
    return url.href
  } catch {
    return null
  }
}

export function youtubeDemoLink(game: any) {
  if (!game) return null
  const youtubeDemoUrl = safeYouTubeUrl(game.youtube_demo_url)
  if (youtubeDemoUrl) return { href: youtubeDemoUrl, label: 'YouTube demo' }
  const demoUrl = safeYouTubeUrl(game.demo_url)
  if (demoUrl) return { href: demoUrl, label: 'YouTube demo' }

  const urls = Array.isArray(game.urls) ? game.urls : []
  const yt = urls.find((row: any) => {
    const typeMarksYoutube = String(row?.type || '')
      .toLowerCase()
      .includes('youtube')
    const url = safeYouTubeUrl(row?.url)
    return Boolean(url && (typeMarksYoutube || /youtu(\.be|be\.com)/i.test(url)))
  })
  const youtubeUrl = safeYouTubeUrl(yt?.url)
  if (youtubeUrl) return { href: youtubeUrl, label: 'YouTube' }
  return null
}

/**
 * Wave 19 — RetroArch `.cht` surface only when Backend says so.
 * Prefer `cheat_surface === 'retroarch'`. Never invent Flask flags here.
 * @param {object | null | undefined} game
 * @returns {boolean}
 */
export function showsRetroarchCheats(game: any) {
  if (!game || typeof game !== 'object') return false
  return (
    String(game.cheat_surface || '')
      .trim()
      .toLowerCase() === 'retroarch'
  )
}

/**
 * Admin path rows from details payload (full_disk_path / server_path / optional admin_paths).
 * Shows the full path string when Backend exposes it (no basename truncation in UI).
 * @param {object} game
 * @returns {{ label: string, path: string }[]}
 */
export function adminPathRows(game: any) {
  if (!game?.is_admin) return []
  const rows: any[] = []
  const seen = new Set()

  function push(label: any, path: any) {
    const trimmed = String(path || '').trim()
    if (!trimmed || seen.has(trimmed)) return
    seen.add(trimmed)
    rows.push({ label, path: trimmed })
  }

  if (Array.isArray(game.admin_paths)) {
    for (const row of game.admin_paths) {
      if (typeof row === 'string') {
        push('Path', row)
      } else if (row && typeof row === 'object') {
        push(row.label || row.kind || 'Path', row.path || row.full_disk_path || row.server_path)
      }
    }
  }

  push('Library folder', game.full_disk_path)
  push('Server path', game.server_path)
  if (game.paths && typeof game.paths === 'object') {
    for (const [key, value] of Object.entries(game.paths)) {
      push(key, value)
    }
  }

  return rows
}

/**
 * Wave 14b — whether a version/extra row may offer Download.
 * Honest when Backend sends `downloadable` / `path_missing`; otherwise assume downloadable.
 * @param {object | null | undefined} row
 * @returns {boolean}
 */
export function isVersionDownloadable(row: any) {
  if (!row || typeof row !== 'object') return false
  if (row.downloadable === false) return false
  if (row.path_missing === true) return false
  return true
}

/**
 * Quiet “Missing on disk” affordance when Backend marks the path gone or not downloadable.
 * @param {object | null | undefined} row
 * @returns {boolean}
 */
export function isVersionPathMissing(row: any) {
  if (!row || typeof row !== 'object') return false
  return row.path_missing === true || row.downloadable === false
}

/**
 * Format size for version rows (string as-is, or humanize bytes when numeric).
 * @param {unknown} size
 * @returns {string | null}
 */
export function formatVersionSize(size: any) {
  if (size == null || size === '') return null
  if (typeof size === 'string') {
    const trimmed = size.trim()
    return trimmed || null
  }
  const bytes = Number(size)
  if (!Number.isFinite(bytes) || bytes < 0) return null
  if (bytes < 1024) return `${Math.round(bytes)} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  const rounded = value >= 10 || unit === 0 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded} ${units[unit]}`
}

/**
 * Disc chips for game details (not tiles — UID-001 cap=2 already fills corners).
 * @param {object} game
 * @returns {{ key: string, text: string, title: string }[]}
 */
export function detailsDiscChips(game: any) {
  if (!game) return []
  const discs = Array.isArray(game.discs) ? game.discs : []
  const parsedCount = Number(game.disc_count)
  const count = Number.isFinite(parsedCount) && parsedCount > 0 ? parsedCount : discs.length
  const multi = Boolean(game.is_multi_disc) || count > 1
  const chips = []
  if (multi || count > 1) {
    chips.push({
      key: 'count',
      text: `${count} discs`,
      title: 'This library title is a multi-disc set',
    })
  } else if (game.disc_index != null && game.disc_index !== '') {
    chips.push({
      key: 'one',
      text: `Disc ${game.disc_index}`,
      title: 'Disc index from the dump name',
    })
  }
  const seen = new Set()
  for (const disc of discs) {
    const idx = disc?.disc_index
    if (idx == null || idx === '') continue
    if (seen.has(idx)) continue
    seen.add(idx)
    chips.push({
      key: `disc-${idx}`,
      text: `Disc ${idx}`,
      title: disc.is_primary ? 'Primary dump' : 'Companion disc',
    })
  }
  return chips
}

/**
 * Extras / DLC rows — prefer Backend `extras` contract; else versions kind=extra.
 * @param {object} game
 * @param {object[]} versions
 * @returns {{ rows: object[], source: 'extras' | 'versions' | 'empty', loading: boolean }}
 */
export function extrasPanelModel(
  game: any,
  versions: any[] = [],
  { loading = false }: LooseProps = {},
) {
  if (loading) {
    return { rows: [], source: 'empty', loading: true }
  }

  if (Array.isArray(game?.extras)) {
    const rows = game.extras.map((row: any) => ({
      id: row.uuid || row.id || row.name || row.label,
      label: row.name || row.label || 'Extra',
      kind: row.extra_kind || row.type || row.kind || 'extra',
      type: row.type || row.extra_kind || row.kind || null,
      on_server: row.on_server,
      size: row.size,
      uuid: row.uuid,
      download_url: isVersionDownloadable(row) ? row.download_url : null,
      path_missing: row.path_missing === true || row.downloadable === false,
      downloadable: isVersionDownloadable(row),
      disc_index: row.disc_index ?? null,
    }))
    return { rows, source: 'extras', loading: false }
  }

  const fromVersions = (Array.isArray(versions) ? versions : [])
    .filter((row) => row.kind === 'extra')
    .map((row) => ({
      id: row.uuid || row.id,
      label: row.label || row.name || 'Extra',
      kind: row.extra_kind || row.type || 'extra',
      type: row.type || row.extra_kind || null,
      on_server: row.on_server,
      size: row.size,
      uuid: row.uuid,
      download_url: isVersionDownloadable(row)
        ? `/download_other/extra/${game?.uuid}/${row.uuid}`
        : null,
      path_missing: isVersionPathMissing(row),
      downloadable: isVersionDownloadable(row),
      disc_index: row.disc_index ?? null,
    }))

  return {
    rows: fromVersions,
    source: fromVersions.length ? 'versions' : 'empty',
    loading: false,
  }
}
