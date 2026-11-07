/** Server-authorized recent titles for the command-palette empty state. */

export const RECENT_TITLES_KEY = 'od.palette.recent'
export const RECENT_TITLES_MAX = 8

/** Remove the pre-privacy-fix origin-global history from this browser profile. */
export function clearLegacyRecentTitles() {
  try {
    window.localStorage?.removeItem(RECENT_TITLES_KEY)
  } catch {
    // Private or restricted storage is optional.
  }
}

export function normalizeRecentTitle(row: any) {
  const uuid = String(row?.uuid || '').trim()
  const name = String(row?.name || '').trim()
  if (!uuid || !name) return null
  return { uuid, name, hint: row?.hint || 'Opened here' }
}

/** Deduplicate and bound recent rows returned for the current signed-in viewer. */
export function mergeSuggestRecent(serverRows: any, limit = RECENT_TITLES_MAX) {
  const cap = Number(limit) > 0 ? Number(limit) : RECENT_TITLES_MAX
  const merged = []
  const seen = new Set()
  for (const row of serverRows || []) {
    const item = normalizeRecentTitle(row)
    if (!item || seen.has(item.uuid)) continue
    seen.add(item.uuid)
    merged.push({
      uuid: item.uuid,
      name: item.name,
      hint: row?.hint || item.hint,
      cover_url: row?.cover_url || null,
    })
    if (merged.length >= cap) break
  }
  return merged
}
