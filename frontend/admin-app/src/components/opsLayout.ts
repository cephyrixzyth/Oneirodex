/** Ops console board layout — same 12-col drag/resize model as Dashboard. */

import {
  DASHBOARD_COLS,
  mergeBoardLayout,
  resolveOverlaps,
  type WidgetItem,
  type WidgetMins,
} from './dashboardLayout'

export const OPS_STORAGE_KEY = 'od-admin-ops-layout-v1'

export const OPS_METRIC_IDS = [
  'build',
  'cpu',
  'load',
  'memory',
  'gpu',
  'rss',
  'db',
  'awake',
  'companions',
  'disk',
  'watch',
  'health',
]

export const OPS_DETAIL_IDS = [
  'detail-system',
  'detail-database',
  'detail-logs',
  'detail-config',
  'detail-theme_assets',
]

const METRIC_MIN = { w: 2, h: 2 }
const PANEL_MIN = { w: 3, h: 3 }
const STATUS_MIN = { w: 6, h: 3 }
const WIDE_MIN = { w: 4, h: 3 }

export function opsWidgetMins(id: string): WidgetMins {
  if (id === 'status') return STATUS_MIN
  if (String(id).startsWith('m-')) return METRIC_MIN
  if (id === 'scans' || id === 'errors' || id === 'recent-log') return WIDE_MIN
  return PANEL_MIN
}

function packMetricRows(metricIds: string[], startY: number): { items: WidgetItem[]; y: number } {
  const items: WidgetItem[] = []
  let y = startY
  const perRow = 4
  for (let i = 0; i < metricIds.length; i += perRow) {
    const rowIds = metricIds.slice(i, i + perRow)
    const unit = Math.floor(DASHBOARD_COLS / rowIds.length)
    rowIds.forEach((id, col) => {
      const isLast = col === rowIds.length - 1
      const width = isLast ? DASHBOARD_COLS - unit * (rowIds.length - 1) : unit
      items.push({ id: `m-${id}`, x: col * unit, y, w: width, h: 2 })
    })
    y += 2
  }
  return { items, y }
}

/**
 * Default Ops pack: status, metric strip, host/services/companions/library,
 * scans/errors, detail panels, recent log. `visibleIds` drops panels that have
 * no data yet so empty frames do not reserve tracks.
 */
export function defaultOpsLayout({ visibleIds }: { visibleIds?: string[] } = {}): WidgetItem[] {
  const visible = visibleIds ? new Set(visibleIds) : null
  const show = (id: string) => !visible || visible.has(id)
  const items: WidgetItem[] = []

  if (show('status')) {
    items.push({ id: 'status', x: 0, y: 0, w: 12, h: 3 })
  }
  let y = show('status') ? 3 : 0

  const metricIds = OPS_METRIC_IDS.filter((id) => show(`m-${id}`))
  const packed = packMetricRows(metricIds, y)
  items.push(...packed.items)
  y = packed.y

  const panels = [
    { id: 'host', w: 6, h: 4 },
    { id: 'services', w: 6, h: 4 },
    { id: 'companions', w: 6, h: 4 },
    { id: 'library', w: 6, h: 4 },
    { id: 'scans', w: 12, h: 4 },
    { id: 'errors', w: 12, h: 3 },
    ...OPS_DETAIL_IDS.map((id) => ({ id, w: 6, h: 4 })),
    { id: 'recent-log', w: 12, h: 5 },
  ].filter((panel) => show(panel.id))

  let x = 0
  let rowH = 0
  for (const panel of panels) {
    if (x + panel.w > DASHBOARD_COLS) {
      x = 0
      y += rowH
      rowH = 0
    }
    items.push({ id: panel.id, x, y, w: panel.w, h: panel.h })
    x += panel.w
    rowH = Math.max(rowH, panel.h)
    if (x >= DASHBOARD_COLS) {
      x = 0
      y += rowH
      rowH = 0
    }
  }
  return resolveOverlaps(items, null, opsWidgetMins)
}

export function loadOpsLayout(visibleIds?: string[]): WidgetItem[] {
  const fallback = () => defaultOpsLayout({ visibleIds })
  if (typeof window === 'undefined' || !window.localStorage) return fallback()
  try {
    const raw = window.localStorage.getItem(OPS_STORAGE_KEY)
    if (!raw) return fallback()
    return mergeBoardLayout(JSON.parse(raw), fallback(), opsWidgetMins)
  } catch {
    return fallback()
  }
}
