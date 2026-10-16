import { DASH_RESIZE_PX_PER_COL, DASH_RESIZE_PX_PER_ROW, type WidgetItem } from './dashboardLayout'

export interface DragState {
  mode: 'move' | 'resize'
  id: string
  originX: number
  originY: number
  lastX: number
  lastY: number
  grabX?: number
  grabY?: number
  /** Resize axis: edge handles lock one axis, the corner moves both. */
  axis?: 'x' | 'y' | 'both'
  start: WidgetItem
  colPitch: number
  rowPitch: number
}

export function prettyId(id: string) {
  const text = id.replace(/^m-/, '').replace(/[-_]+/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Grid steps for a resize drag, honouring the handle's axis. */
export function resizeDims(drag: DragState, x: number, y: number) {
  const axis = drag.axis ?? 'both'
  const w =
    axis === 'y'
      ? drag.start.w
      : drag.start.w + Math.round((x - drag.originX) / (drag.colPitch * DASH_RESIZE_PX_PER_COL))
  const h =
    axis === 'x'
      ? drag.start.h
      : drag.start.h + Math.round((y - drag.originY) / (drag.rowPitch * DASH_RESIZE_PX_PER_ROW))
  return { w, h }
}

export function isInteractiveTarget(target: EventTarget | null) {
  if (!(target instanceof Element)) return true
  return Boolean(
    target.closest(
      'a, button, input, select, textarea, label, [role="button"], [contenteditable="true"]',
    ),
  )
}
