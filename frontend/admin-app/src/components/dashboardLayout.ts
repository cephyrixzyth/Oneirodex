/** Shared 12-column widget board layout — Dashboard + Ops. */

export interface WidgetItem {
  id: string
  x: number
  y: number
  w: number
  h: number
}

export type WidgetMins = { w: number; h: number }
export type WidgetMinsFn = (id: string) => WidgetMins

export const DASHBOARD_COLS = 12
/** Bumped when the board interaction model changes so sticky bad layouts reset. */
export const DASHBOARD_STORAGE_KEY = 'od-admin-dashboard-layout-v4'
/** Hard cap so a bad pitch cannot shove widgets into the void. */
export const DASHBOARD_MAX_Y = 48

export const DASHBOARD_METRIC_IDS = [
  // First: after a deploy this is the tile an operator came to read.
  'build',
  'libraries',
  'games',
  'health',
  'scans',
  'disk',
  'load',
  'rss',
  'db',
  'awake',
  'companions',
]

/**
 * Widgets that exist but start hidden; the "Add widget" menu brings them in.
 * They live in the default layout (below everything else) so layout merging
 * keeps their ids; the board filters them out until the admin adds them.
 */
export const DASHBOARD_OPTIONAL_IDS = ['m-cpu', 'm-memory', 'm-unmatched', 'scan-jobs']

export const DASHBOARD_WIDGET_LABELS: Record<string, string> = {
  status: 'Health banner',
  'm-build': 'Build',
  'm-libraries': 'Libraries',
  'm-games': 'Games',
  'm-health': 'Library health',
  'm-scans': 'Scans',
  'm-disk': 'Disk',
  'm-load': 'Load average',
  'm-rss': 'Process memory',
  'm-db': 'DB ping',
  'm-awake': 'Readyz',
  'm-companions': 'Companions',
  'm-cpu': 'CPU',
  'm-memory': 'Memory',
  'm-unmatched': 'Unmatched folders',
  'scan-jobs': 'Active scan jobs',
  host: 'Host meters',
  companions: 'Companions by kind',
  errors: 'Recent errors',
}

const METRIC_MIN = { w: 2, h: 2 }
const PANEL_MIN = { w: 3, h: 3 }
const STATUS_MIN = { w: 6, h: 2 }

export function widgetMins(id: string): WidgetMins {
  if (id === 'status') return STATUS_MIN
  if (id === 'host' || id === 'companions' || id === 'errors' || id === 'scan-jobs')
    return PANEL_MIN
  return METRIC_MIN
}

/**
 * Default pack: metrics fill the row (no orphan empty tracks), then host +
 * companions side by side, optional errors full width.
 */
export function defaultDashboardLayout({
  hasErrors = false,
}: { hasErrors?: boolean } = {}): WidgetItem[] {
  const items: WidgetItem[] = [{ id: 'status', x: 0, y: 0, w: 12, h: 2 }]
  let y = 2
  const perRow = 4
  const ids = DASHBOARD_METRIC_IDS
  for (let i = 0; i < ids.length; i += perRow) {
    const rowIds = ids.slice(i, i + perRow)
    const w = Math.floor(DASHBOARD_COLS / rowIds.length)
    rowIds.forEach((id, col) => {
      const isLast = col === rowIds.length - 1
      const width = isLast ? DASHBOARD_COLS - w * (rowIds.length - 1) : w
      items.push({ id: `m-${id}`, x: col * w, y, w: width, h: 2 })
    })
    y += 2
  }
  items.push({ id: 'host', x: 0, y, w: 6, h: 4 })
  items.push({ id: 'companions', x: 6, y, w: 6, h: 4 })
  y += 4
  if (hasErrors) {
    items.push({ id: 'errors', x: 0, y, w: 12, h: 3 })
    y += 3
  }
  // Optional widgets, hidden until added (see DASHBOARD_OPTIONAL_IDS).
  items.push({ id: 'm-cpu', x: 0, y, w: 3, h: 2 })
  items.push({ id: 'm-memory', x: 3, y, w: 3, h: 2 })
  items.push({ id: 'm-unmatched', x: 6, y, w: 3, h: 2 })
  items.push({ id: 'scan-jobs', x: 0, y: y + 2, w: 12, h: 3 })
  return items
}

export function clampWidget(
  item: Partial<WidgetItem> & { id: string },
  minsFn: WidgetMinsFn = widgetMins,
): WidgetItem {
  const mins = minsFn(item.id)
  const w = Math.max(mins.w, Math.min(DASHBOARD_COLS, Number(item.w) || mins.w))
  const h = Math.max(mins.h, Math.min(16, Number(item.h) || mins.h))
  const x = Math.max(0, Math.min(DASHBOARD_COLS - w, Number(item.x) || 0))
  const y = Math.max(0, Math.min(DASHBOARD_MAX_Y, Number(item.y) || 0))
  return { id: item.id, x, y, w, h }
}

/**
 * Resolve a CSS length used for row tracks. `getPropertyValue('--od-dash-row')`
 * returns `3.5rem` (not px) — `parseFloat` alone yields 3.5 and makes drag drop
 * widgets ~16× too far down the board.
 */
export function cssLengthToPx(raw: string | null | undefined, element?: Element | null): number {
  const value = String(raw || '').trim()
  if (!value) return 0
  const amount = parseFloat(value)
  if (!Number.isFinite(amount)) return 0
  if (value.endsWith('rem')) {
    const root = element?.ownerDocument?.documentElement || document.documentElement
    const fontSize = parseFloat(getComputedStyle(root).fontSize) || 16
    return amount * fontSize
  }
  if (value.endsWith('em') && element) {
    const fontSize = parseFloat(getComputedStyle(element).fontSize) || 16
    return amount * fontSize
  }
  return amount
}

/**
 * Column / row pitch for pointer → grid mapping (cell size + gap).
 * Prefer a resolved `gridTemplateRows` px track; fall back to `--od-dash-row`.
 */
export function boardCellMetrics(board: Element | null | undefined) {
  if (!board) {
    return { colPitch: 1, rowPitch: 56 }
  }
  const rect = board.getBoundingClientRect()
  const style = getComputedStyle(board)
  const colGap = parseFloat(style.columnGap || style.gap) || 0
  const rowGap = parseFloat(style.rowGap || style.gap) || 0
  const colPitch = (rect.width + colGap) / DASHBOARD_COLS

  let rowTrack = 0
  const tracks = String(style.gridTemplateRows || '').trim()
  const pxTrack = tracks.match(/([\d.]+)px/)
  if (pxTrack) {
    rowTrack = parseFloat(pxTrack[1])
  }
  if (!(rowTrack > 0)) {
    rowTrack = cssLengthToPx(style.getPropertyValue('--od-dash-row'), board) || 56
  }
  return {
    colPitch: colPitch > 0 ? colPitch : 1,
    rowPitch: rowTrack + rowGap,
    rowTrack,
    colGap,
    rowGap,
  }
}

/** How many row tracks a content height needs (ceil, at least minH). */
export function rowsForContentHeight(heightPx: number, rowPitch: number, minH = 2): number {
  const pitch = rowPitch > 0 ? rowPitch : 56
  return Math.max(minH, Math.min(16, Math.ceil(heightPx / pitch)))
}

export function overlaps(a: WidgetItem, b: WidgetItem): boolean {
  return a.id !== b.id && a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}

/**
 * Push overlapping widgets down, but never move `pinnedId`.
 * Used on drop so the widget you placed stays where you put it.
 */
export function resolveOverlaps(
  layout: (Partial<WidgetItem> & { id: string })[],
  pinnedId: string | null = null,
  minsFn: WidgetMinsFn = widgetMins,
  fixedIds: readonly string[] = [],
): WidgetItem[] {
  const items = layout.map((item) => clampWidget(item, minsFn))
  const fixed = new Set(fixedIds)
  const anchors = items.filter((item) => fixed.has(item.id))
  const pinned = pinnedId ? items.find((item) => item.id === pinnedId && !fixed.has(item.id)) : null
  const rest = items
    .filter((item) => !fixed.has(item.id) && item.id !== pinnedId)
    .sort((a, b) => a.y - b.y || a.x - b.x)

  // Locked widgets are obstacles: they never move, everything routes round them.
  const placed: WidgetItem[] = [...anchors]
  if (pinned) {
    let next = { ...pinned }
    let guard = 0
    while (guard < 64 && placed.some((other) => overlaps(next, other))) {
      next = { ...next, y: next.y + 1 }
      guard += 1
    }
    placed.push(next)
  }
  for (const item of rest) {
    let next = { ...item }
    let guard = 0
    while (guard < 64 && placed.some((other) => overlaps(next, other))) {
      next = { ...next, y: next.y + 1 }
      guard += 1
    }
    placed.push(next)
  }
  return placed
}

/** Apply size/position without shoving the active widget away mid-drag. */
export function patchWidget(
  layout: WidgetItem[],
  id: string,
  patch: Partial<WidgetItem>,
  minsFn: WidgetMinsFn = widgetMins,
): WidgetItem[] {
  return layout.map((item) =>
    item.id === id ? clampWidget({ ...item, ...patch, id }, minsFn) : item,
  )
}

/**
 * Commit a move: same-size overlap swaps; otherwise pin the mover and nudge
 * everyone else down.
 */
export function commitMove(
  layout: WidgetItem[],
  id: string,
  x: number | undefined,
  y: number | undefined,
  minsFn: WidgetMinsFn = widgetMins,
  fixedIds: readonly string[] = [],
): WidgetItem[] {
  const current = layout.find((item) => item.id === id)
  if (!current || fixedIds.includes(id)) return layout
  const moved = clampWidget({ ...current, x, y }, minsFn)
  const hit = layout.find((item) => item.id !== id && overlaps(moved, item))
  if (hit && hit.w === moved.w && hit.h === moved.h && !fixedIds.includes(hit.id)) {
    return layout.map((item) => {
      if (item.id === id) return moved
      if (item.id === hit.id) {
        return clampWidget({ ...hit, x: current.x, y: current.y }, minsFn)
      }
      return item
    })
  }
  return resolveOverlaps(patchWidget(layout, id, { x, y }, minsFn), id, minsFn, fixedIds)
}

export function commitResize(
  layout: WidgetItem[],
  id: string,
  w: number | undefined,
  h: number | undefined,
  minsFn: WidgetMinsFn = widgetMins,
  fixedIds: readonly string[] = [],
): WidgetItem[] {
  if (fixedIds.includes(id)) return layout
  return resolveOverlaps(patchWidget(layout, id, { w, h }, minsFn), id, minsFn, fixedIds)
}

/** @deprecated — use commitMove / commitResize; kept for older call sites. */
export function updateWidget(
  layout: WidgetItem[],
  id: string,
  patch: Partial<WidgetItem>,
  minsFn: WidgetMinsFn = widgetMins,
): WidgetItem[] {
  if (patch.w != null || patch.h != null) {
    return commitResize(layout, id, patch.w ?? undefined, patch.h ?? undefined, minsFn)
  }
  return commitMove(layout, id, patch.x, patch.y, minsFn)
}

/**
 * Merge a stored layout against a freshly built default (add new widgets, drop
 * unknown ids). Shared by Dashboard and Ops.
 */
export function mergeBoardLayout(
  stored: unknown,
  fallback: WidgetItem[],
  minsFn: WidgetMinsFn = widgetMins,
): WidgetItem[] {
  if (!Array.isArray(stored) || !stored.length) {
    return resolveOverlaps(fallback, null, minsFn)
  }
  const byId = new Map(
    (stored as (Partial<WidgetItem> & { id: string })[]).map((item) => [
      item.id,
      clampWidget(item, minsFn),
    ]),
  )
  const ids = new Set(fallback.map((item) => item.id))
  const merged = fallback.map((item) => byId.get(item.id) || item)
  for (const item of byId.values()) {
    if (ids.has(item.id) && !merged.some((row) => row.id === item.id)) {
      merged.push(item)
    }
  }
  return resolveOverlaps(
    merged.filter((item) => ids.has(item.id)),
    null,
    minsFn,
  )
}

export function loadDashboardLayout(hasErrors: boolean): WidgetItem[] {
  const fallback = defaultDashboardLayout({ hasErrors })
  if (typeof window === 'undefined' || !window.localStorage) return fallback
  try {
    const raw = window.localStorage.getItem(DASHBOARD_STORAGE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    let merged = mergeBoardLayout(parsed, fallback)
    if (!hasErrors) {
      return resolveOverlaps(merged.filter((item) => item.id !== 'errors'))
    }
    if (!merged.some((item) => item.id === 'errors')) {
      merged = [
        ...merged,
        ...defaultDashboardLayout({ hasErrors: true }).filter((i) => i.id === 'errors'),
      ]
    }
    return resolveOverlaps(merged)
  } catch {
    return fallback
  }
}

export function saveDashboardLayout(layout: WidgetItem[]): void {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    window.localStorage.setItem(
      DASHBOARD_STORAGE_KEY,
      JSON.stringify(layout.map((item) => clampWidget(item))),
    )
  } catch {
    /* private mode / quota — layout still works for the session */
  }
}

export function loadBoardLayout({
  storageKey,
  defaultLayout,
  minsFn = widgetMins,
}: {
  storageKey: string
  defaultLayout: () => WidgetItem[]
  minsFn?: WidgetMinsFn
}): WidgetItem[] {
  const fallback = defaultLayout()
  if (typeof window === 'undefined' || !window.localStorage) return fallback
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return fallback
    return mergeBoardLayout(JSON.parse(raw), fallback, minsFn)
  } catch {
    return fallback
  }
}

export function saveBoardLayout(
  storageKey: string,
  layout: WidgetItem[],
  minsFn: WidgetMinsFn = widgetMins,
): void {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    window.localStorage.setItem(
      storageKey,
      JSON.stringify(layout.map((item) => clampWidget(item, minsFn))),
    )
  } catch {
    /* private mode / quota */
  }
}

/** Pixels of pointer travel per grid step — > cell size so resize is controllable. */
export const DASH_RESIZE_PX_PER_COL = 1.85
export const DASH_RESIZE_PX_PER_ROW = 1.85
export const DASH_MOVE_PX_PER_COL = 1
export const DASH_MOVE_PX_PER_ROW = 1

/** Size presets offered in each widget's menu (columns of 12, rows of the board track). */
export type SizePreset = 'small' | 'medium' | 'large' | 'full'

export const SIZE_PRESET_LABELS: Record<SizePreset, string> = {
  small: 'Small',
  medium: 'Medium',
  large: 'Large',
  full: 'Full width',
}

/** Resize to a preset, keeping the widget's rows unless the preset implies more. */
export function applySizePreset(
  layout: WidgetItem[],
  id: string,
  preset: SizePreset,
  minsFn: WidgetMinsFn = widgetMins,
  fixedIds: readonly string[] = [],
): WidgetItem[] {
  const current = layout.find((item) => item.id === id)
  if (!current) return layout
  const cols: Record<SizePreset, number> = { small: 3, medium: 6, large: 9, full: DASHBOARD_COLS }
  const w = cols[preset]
  // Keep the left edge when it still fits, otherwise slide left.
  const x = Math.min(current.x, DASHBOARD_COLS - w)
  const moved = commitResize(
    patchWidget(layout, id, { x }, minsFn),
    id,
    w,
    current.h,
    minsFn,
    fixedIds,
  )
  return moved
}

/** Keyboard nudge: arrows move, shift+arrows resize. Returns the layout unchanged when locked. */
export function nudgeWidget(
  layout: WidgetItem[],
  id: string,
  dx: number,
  dy: number,
  resize: boolean,
  minsFn: WidgetMinsFn = widgetMins,
  fixedIds: readonly string[] = [],
): WidgetItem[] {
  const current = layout.find((item) => item.id === id)
  if (!current) return layout
  if (resize) return commitResize(layout, id, current.w + dx, current.h + dy, minsFn, fixedIds)
  return commitMove(layout, id, current.x + dx, current.y + dy, minsFn, fixedIds)
}

/** Place a (re)added widget under everything else, at its preferred size. */
export function appendWidget(
  layout: WidgetItem[],
  id: string,
  size: { w: number; h: number },
  minsFn: WidgetMinsFn = widgetMins,
  fixedIds: readonly string[] = [],
): WidgetItem[] {
  if (layout.some((item) => item.id === id)) return layout
  const bottom = layout.reduce((max, item) => Math.max(max, item.y + item.h), 0)
  return resolveOverlaps(
    [...layout, { id, x: 0, y: bottom, w: size.w, h: size.h }],
    null,
    minsFn,
    fixedIds,
  )
}

/** Small persisted id sets (pinned / hidden widgets), per board. */
export function loadIdSet(key: string): string[] | null {
  if (typeof window === 'undefined' || !window.localStorage) return null
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : null
  } catch {
    return null
  }
}

export function saveIdSet(key: string, ids: readonly string[]): void {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    window.localStorage.setItem(key, JSON.stringify([...ids]))
  } catch {
    /* private mode / quota */
  }
}
