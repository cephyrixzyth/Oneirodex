import { MAX_INDIVIDUAL_TOASTS, stackSummaryMessage } from './toastStack.js'

/**
 * Soft-detect “N games added to Library X” notifications from watch/scan.
 * Backend may send `kind` / `type` or only title/body — tolerate either.
 *
 * Shared by member-app and admin-app (UX-B7): staff watching a scan live on
 * admin pages, members browsing the library.
 */

/**
 * A notification row as the poll endpoints hand it over. Every field is
 * optional — the backend is mid-migration and some rows carry only a title.
 */
export interface ScanNotificationRow {
  id?: string | number
  uuid?: string
  created_at?: string
  kind?: string
  type?: string
  category?: string
  title?: string
  body?: string
  message?: string
  library?: string
  library_name?: string
  library_uuid?: string
  count?: number
  added?: number
  data?: {
    library?: string
    library_name?: string
    count?: number
  }
}

/** A batch of rows collapsed to one entry per library. */
export interface ScanToastGroup {
  key: string
  rows: ScanNotificationRow[]
  total: number
  library: string
}

/** One toast line for a whole poll's worth of groups. */
export interface BurstToastMessage {
  message: string
  count: number
  rows: ScanNotificationRow[]
}

const KIND_HINTS = new Set([
  'library_games_added',
  'library_added',
  'library_scan_added',
  'games_added',
  'library_incremental',
])

const TITLE_BODY_RE = /\d+\s+games?\s+added\s+to\s+library/i

const SEEN_KEY = 'oneirodex.libraryScanToasts.seen.v1'

export function isLibraryGamesAddedNotification(
  row: ScanNotificationRow | null | undefined,
): boolean {
  if (!row || typeof row !== 'object') {
    return false
  }
  const kind = String(row.kind || row.type || row.category || '')
    .trim()
    .toLowerCase()
  if (KIND_HINTS.has(kind)) {
    return true
  }
  const text = `${row.title || ''} ${row.body || ''} ${row.message || ''}`
  return TITLE_BODY_RE.test(text)
}

const COUNT_RE = /(\d+)\s+games?\s+added/i
const LIBRARY_RE = /added\s+to\s+library\s+(.+?)\s*$/i

/** Library a notification belongs to, for grouping. Falls back to its own id
 *  so an unattributable row still toasts once rather than merging with others. */
export function libraryKeyOf(row: ScanNotificationRow | null | undefined): string {
  const named =
    row?.library ||
    row?.library_name ||
    row?.library_uuid ||
    row?.data?.library ||
    row?.data?.library_name
  if (named) return String(named)

  const text = `${row?.title || ''} ${row?.body || ''} ${row?.message || ''}`
  const match = LIBRARY_RE.exec(text.trim())
  if (match) return match[1].trim()

  return `__row_${row?.id ?? row?.uuid ?? row?.created_at ?? Math.random()}`
}

/** Games added, for summing a burst into one figure. Unknown counts as 1 so a
 *  countless notification still contributes rather than reading as zero. */
export function addedCountOf(row: ScanNotificationRow | null | undefined): number {
  const explicit = Number(row?.count ?? row?.added ?? row?.data?.count)
  if (Number.isFinite(explicit) && explicit > 0) return explicit

  const text = `${row?.title || ''} ${row?.body || ''} ${row?.message || ''}`
  const match = COUNT_RE.exec(text)
  return match ? Number(match[1]) : 1
}

/**
 * Collapse a batch of notifications to one entry per library (GT-B11).
 *
 * A scan emits a notification per increment, so a library of any size produced
 * a stream of near-identical toasts — "3 games added", "2 games added", "5
 * games added" — which is noise standing in for one useful fact. Grouping by
 * library and summing gives a single toast per library per poll, which is the
 * granularity anyone actually wants.
 */
export function groupLibraryScanToasts(rows: ScanNotificationRow[]): ScanToastGroup[] {
  const groups = new Map<string, ScanToastGroup>()
  for (const row of rows) {
    const key = libraryKeyOf(row)
    let group = groups.get(key)
    if (!group) {
      group = { key, rows: [], total: 0, library: key.startsWith('__row_') ? '' : key }
      groups.set(key, group)
    }
    group.rows.push(row)
    group.total += addedCountOf(row)
  }
  return [...groups.values()]
}

/** One line for a whole library's batch. */
export function groupedToastMessage(group: ScanToastGroup): string {
  if (group.rows.length === 1) {
    return libraryGamesAddedToastMessage(group.rows[0])
  }
  const games = `${group.total} game${group.total === 1 ? '' : 's'}`
  return group.library ? `${games} added to ${group.library}` : `${games} added`
}

/**
 * A small number of libraries stay named; larger bursts become one
 * “N notifications” toast so notices cannot cover the active page.
 */
export function burstToastMessages(
  groups: Array<Pick<ScanToastGroup, 'rows'>> | null | undefined,
  options: { maxIndividual?: number } = {},
): BurstToastMessage[] {
  const list = Array.isArray(groups) ? groups : []
  if (list.length === 0) {
    return []
  }
  const allRows = list.flatMap((group) => group.rows || [])
  const maxIndividual =
    Number.isInteger(options.maxIndividual) && options.maxIndividual! > 0
      ? options.maxIndividual!
      : MAX_INDIVIDUAL_TOASTS
  if (list.length > maxIndividual) {
    return [
      {
        message: stackSummaryMessage(list.length),
        count: list.length,
        rows: allRows,
      },
    ]
  }
  return list.map((group) => ({
    message: groupedToastMessage(group as ScanToastGroup),
    count: 1,
    rows: group.rows || [],
  }))
}

export function libraryGamesAddedToastMessage(row: ScanNotificationRow | null | undefined): string {
  const title = String(row?.title || '').trim()
  if (title) {
    return title
  }
  const body = String(row?.body || row?.message || '').trim()
  if (body) {
    return body
  }
  return 'Games added to library'
}

function readSeenIds(): Set<string> {
  try {
    const raw = sessionStorage.getItem(SEEN_KEY)
    if (!raw) {
      return new Set()
    }
    const parsed: unknown = JSON.parse(raw)
    return new Set(Array.isArray(parsed) ? parsed.map(String) : [])
  } catch {
    return new Set()
  }
}

function writeSeenIds(ids: Set<string>): void {
  try {
    const list = [...ids].slice(-80)
    sessionStorage.setItem(SEEN_KEY, JSON.stringify(list))
  } catch {
    // ignore quota / private mode
  }
}

/** Mark a notification id as toasted this session. */
export function markLibraryScanToastSeen(id: string | number | null | undefined): void {
  if (id == null || id === '') {
    return
  }
  const seen = readSeenIds()
  seen.add(String(id))
  writeSeenIds(seen)
}

export function wasLibraryScanToastSeen(id: string | number | null | undefined): boolean {
  if (id == null || id === '') {
    return false
  }
  return readSeenIds().has(String(id))
}

/** Pick unseen library-added rows to toast (newest first, capped). */
export function pickUnseenLibraryScanToasts(
  notifications: ScanNotificationRow[] | null | undefined,
  options: { limit?: number } = {},
): ScanNotificationRow[] {
  const limit = options.limit ?? 50
  const rows = Array.isArray(notifications) ? notifications : []
  const out: ScanNotificationRow[] = []
  for (const row of rows) {
    if (!isLibraryGamesAddedNotification(row)) {
      continue
    }
    const id = row.id ?? row.uuid ?? row.created_at ?? row.title
    if (wasLibraryScanToastSeen(id)) {
      continue
    }
    out.push(row)
    if (out.length >= limit) {
      break
    }
  }
  return out
}
