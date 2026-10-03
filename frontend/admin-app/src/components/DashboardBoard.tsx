import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { AdminPageActions } from './AdminPageActions'
import { AddWidgetMenu, WidgetChrome } from './WidgetChrome'
import { useBoardPrefs } from '../hooks/useBoardPrefs'
import {
  DASHBOARD_STORAGE_KEY,
  appendWidget,
  applySizePreset,
  nudgeWidget,
  type SizePreset,
  DASH_RESIZE_PX_PER_COL,
  DASH_RESIZE_PX_PER_ROW,
  boardCellMetrics,
  commitMove,
  commitResize,
  defaultDashboardLayout,
  loadBoardLayout,
  loadDashboardLayout,
  mergeBoardLayout,
  rowsForContentHeight,
  saveBoardLayout,
  saveDashboardLayout,
  widgetMins,
  type WidgetItem,
  type WidgetMinsFn,
} from './dashboardLayout'

interface DragState {
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

type PreviewState =
  | { id: string; mode: 'move'; dx: number; dy: number }
  | { id: string; mode: 'resize'; w: number; h: number; start: WidgetItem }

function prettyId(id: string) {
  const text = id.replace(/^m-/, '').replace(/[-_]+/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Grid steps for a resize drag, honouring the handle's axis. */
function resizeDims(drag: DragState, x: number, y: number) {
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

function isInteractiveTarget(target: EventTarget | null) {
  if (!(target instanceof Element)) return true
  return Boolean(
    target.closest(
      'a, button, input, select, textarea, label, [role="button"], [contenteditable="true"]',
    ),
  )
}

/**
 * Draggable / resizable board shell (12-col grid) — Dashboard + Ops.
 *
 * Move uses a transform preview so the widget follows the pointer without
 * reflowing the CSS grid under the cursor. Grid coords commit on release.
 * No grab bar — drag from empty chrome; interactive controls stay clickable.
 * Resize is corner-only.
 *
 * Optional `storageKey` + `defaultLayout` switch the board onto a custom
 * persistence profile (Ops). Without them it keeps the Dashboard layout keys.
 *
 * Reset sits in the centre page slot (Users / member Library pattern).
 * Refresh sits in the trail; Updated appears as a hover popup on that control.
 */
export function DashboardBoard({
  widgets,
  hasErrors = false,
  asOf = null,
  onRefresh = null,
  refreshing = false,
  refreshDisabled = false,
  storageKey = null,
  defaultLayout = null,
  minsFn = widgetMins,
  layoutLabel = 'Dashboard layout',
  statusLabel = 'Dashboard status',
  refreshAriaLabel = 'Refresh dashboard',
  boardAriaLabel = null,
  widgetLabels = {},
  defaultHidden = [],
}: {
  widgets: Record<string, ReactNode>
  hasErrors?: boolean
  asOf?: string | null
  onRefresh?: (() => void) | null
  refreshing?: boolean
  refreshDisabled?: boolean
  storageKey?: string | null
  defaultLayout?: (() => WidgetItem[]) | null
  minsFn?: WidgetMinsFn
  layoutLabel?: string
  statusLabel?: string
  refreshAriaLabel?: string
  boardAriaLabel?: string | null
  /** Names shown in each widget's controls and the Add widget menu. */
  widgetLabels?: Record<string, string>
  /** Widgets that start off the board until the admin adds them. */
  defaultHidden?: readonly string[]
}) {
  const asOfId = useId()
  const isCustom = Boolean(storageKey && typeof defaultLayout === 'function')

  const [layout, setLayout] = useState<WidgetItem[]>(() => {
    if (isCustom && storageKey && defaultLayout) {
      return loadBoardLayout({ storageKey, defaultLayout, minsFn })
    }
    return loadDashboardLayout(hasErrors)
  })
  const prefs = useBoardPrefs(
    isCustom && storageKey ? storageKey : DASHBOARD_STORAGE_KEY,
    defaultHidden,
  )
  const { pinned, hidden } = prefs
  const [addOpen, setAddOpen] = useState(false)
  const labelFor = useCallback((id: string) => widgetLabels[id] || prettyId(id), [widgetLabels])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const boardRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef<DragState | null>(null)

  const visibleKey = useMemo(
    () =>
      Object.keys(widgets)
        .filter((id) => widgets[id])
        .sort()
        .join('|'),
    [widgets],
  )

  useEffect(() => {
    if (!isCustom || !defaultLayout) return
    setLayout((prev) => mergeBoardLayout(prev, defaultLayout(), minsFn))
  }, [isCustom, visibleKey, defaultLayout, minsFn])

  useEffect(() => {
    if (isCustom) return
    setLayout((prev) => {
      const ids = new Set(prev.map((item) => item.id))
      if (hasErrors && !ids.has('errors')) {
        return loadDashboardLayout(true)
      }
      if (!hasErrors && ids.has('errors')) {
        return prev.filter((item) => item.id !== 'errors')
      }
      return prev
    })
  }, [hasErrors, isCustom])

  useEffect(() => {
    if (isCustom && storageKey) {
      saveBoardLayout(storageKey, layout, minsFn)
      return
    }
    saveDashboardLayout(layout)
  }, [layout, isCustom, storageKey, minsFn])

  // Hidden widgets take no space: drop them from the layout whenever either changes.
  useEffect(() => {
    setLayout((prev) =>
      prev.some((item) => hidden.includes(item.id))
        ? prev.filter((item) => !hidden.includes(item.id))
        : prev,
    )
  }, [layout, hidden])

  // Banner and metric tiles grow to fit their text (wrapped hints, issue folds);
  // a clipped tile is worse than a taller one. Panels keep their own scroll.
  //
  // The measure (scrollHeight) and the setLayout write are deferred into
  // requestAnimationFrame, and the ResizeObserver callback only *schedules* that
  // rAF rather than measuring+writing inline. The observer watches .od-dash__body,
  // whose height the write changes, so doing both synchronously in the callback is
  // a read->write->re-observe loop within one frame — which pins the main thread
  // when a browser extension (password managers) is also re-measuring on every DOM
  // mutation. Tiles only ever grow, so the loop converges. Deps are
  // [visibleKey, hiddenKey, minsFn], not [widgets, layout.length]: `widgets` is a
  // fresh object each parent render (poll tick, ellipsis tick).
  const hiddenKey = hidden.join('|')
  const pinnedRef = useRef<string[]>(pinned)
  pinnedRef.current = pinned
  useEffect(() => {
    const board = boardRef.current
    if (!board) return undefined
    const hosts = Array.from(board.querySelectorAll('[data-fit="true"] > .od-dash__body'))
    if (!hosts.length) return undefined

    let raf = 0
    let disposed = false

    const measureAndCommit = () => {
      raf = 0
      if (disposed) return
      const metrics = boardCellMetrics(board)
      const needs = new Map<string, number>()
      for (const host of hosts) {
        const id = (host.parentElement as HTMLElement | null)?.dataset.widget
        if (!id || pinnedRef.current.includes(id)) continue
        const inner = host.firstElementChild
        const height = Math.max(host.scrollHeight, inner ? inner.scrollHeight : 0)
        needs.set(id, rowsForContentHeight(height, metrics.rowPitch, minsFn(id).h))
      }
      setLayout((prev) => {
        let next = prev
        for (const [id, need] of needs) {
          const current = next.find((item) => item.id === id)
          if (!current || current.h >= need) continue
          next = commitResize(next, id, current.w, need, minsFn, pinnedRef.current)
        }
        return next
      })
    }

    const schedule = () => {
      if (raf) return
      const req =
        typeof requestAnimationFrame === 'function'
          ? requestAnimationFrame
          : (cb: () => void) => window.setTimeout(cb, 0)
      raf = req(measureAndCommit)
    }

    schedule()
    if (typeof ResizeObserver === 'undefined') {
      return () => {
        disposed = true
      }
    }
    const observer = new ResizeObserver(schedule)
    hosts.forEach((host) => observer.observe(host))
    return () => {
      disposed = true
      if (raf && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(raf)
      observer.disconnect()
    }
  }, [visibleKey, hiddenKey, minsFn])

  const byId = useMemo(() => {
    const map = new Map<string, WidgetItem>()
    layout.forEach((item) => map.set(item.id, item))
    return map
  }, [layout])

  const endDrag = useCallback(() => {
    const drag = dragRef.current
    dragRef.current = null
    setActiveId(null)
    setPreview(null)
    if (!drag) return

    if (drag.mode === 'move') {
      const board = boardRef.current
      if (!board) return
      const rect = board.getBoundingClientRect()
      const { colPitch, rowPitch } = boardCellMetrics(board)
      const left = drag.lastX - (drag.grabX ?? 0)
      const top = drag.lastY - (drag.grabY ?? 0)
      const x = Math.round((left - rect.left) / colPitch)
      const y = Math.round((top - rect.top) / rowPitch)
      setLayout((prev) => commitMove(prev, drag.id, x, y, minsFn, pinnedRef.current))
      return
    }

    const { w, h } = resizeDims(drag, drag.lastX, drag.lastY)
    setLayout((prev) => commitResize(prev, drag.id, w, h, minsFn, pinnedRef.current))
  }, [minsFn])

  useEffect(() => {
    function onMove(event: PointerEvent) {
      const drag = dragRef.current
      if (!drag) return
      drag.lastX = event.clientX
      drag.lastY = event.clientY
      if (drag.mode === 'move') {
        setPreview({
          id: drag.id,
          dx: event.clientX - drag.originX,
          dy: event.clientY - drag.originY,
          mode: 'move',
        })
        return
      }
      const { w, h } = resizeDims(drag, event.clientX, event.clientY)
      setPreview({ id: drag.id, w, h, mode: 'resize', start: drag.start })
    }

    function onUp() {
      if (!dragRef.current) return
      endDrag()
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [endDrag])

  const beginMove = useCallback(
    (id: string, event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return
      if (isInteractiveTarget(event.target)) return
      if (pinnedRef.current.includes(id)) return
      const board = boardRef.current
      const item = byId.get(id)
      const host = event.currentTarget
      if (!board || !item || !(host instanceof Element)) return
      const hostRect = host.getBoundingClientRect()
      const { colPitch, rowPitch } = boardCellMetrics(board)
      dragRef.current = {
        mode: 'move',
        id,
        originX: event.clientX,
        originY: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
        grabX: event.clientX - hostRect.left,
        grabY: event.clientY - hostRect.top,
        start: { ...item },
        colPitch,
        rowPitch,
      }
      setActiveId(id)
      setPreview({ id, dx: 0, dy: 0, mode: 'move' })
      event.preventDefault()
    },
    [byId],
  )

  const beginResize = useCallback(
    (
      id: string,
      event: ReactPointerEvent<HTMLButtonElement>,
      axis: 'x' | 'y' | 'both' = 'both',
    ) => {
      if (event.button !== 0) return
      if (pinnedRef.current.includes(id)) return
      const board = boardRef.current
      const item = byId.get(id)
      if (!board || !item) return
      const { colPitch, rowPitch } = boardCellMetrics(board)
      dragRef.current = {
        mode: 'resize',
        id,
        axis,
        originX: event.clientX,
        originY: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
        start: { ...item },
        colPitch,
        rowPitch,
      }
      setActiveId(id)
      setPreview({ id, w: item.w, h: item.h, mode: 'resize', start: item })
      event.preventDefault()
      event.stopPropagation()
    },
    [byId],
  )

  const defaultSize = useCallback(
    (id: string) => {
      const source =
        isCustom && defaultLayout ? defaultLayout() : defaultDashboardLayout({ hasErrors: true })
      const found = source.find((item) => item.id === id)
      return found ? { w: found.w, h: found.h } : { w: 4, h: 2 }
    },
    [isCustom, defaultLayout],
  )

  function addWidget(id: string) {
    prefs.show(id)
    setLayout((prev) => appendWidget(prev, id, defaultSize(id), minsFn, pinned))
    setAddOpen(false)
  }

  function hideWidget(id: string) {
    setLayout((prev) => prev.filter((item) => item.id !== id))
    prefs.hide(id)
  }

  function onItemKeyDown(id: string, event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return
    const keys: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    }
    const step = keys[event.key]
    if (!step) return
    event.preventDefault()
    setLayout((prev) => nudgeWidget(prev, id, step[0], step[1], event.shiftKey, minsFn, pinned))
  }

  function resetLayout() {
    prefs.reset()
    setAddOpen(false)
    if (isCustom && storageKey && defaultLayout) {
      try {
        window.localStorage?.removeItem(storageKey)
      } catch {
        /* private mode */
      }
      setLayout(defaultLayout())
      return
    }
    setLayout(defaultDashboardLayout({ hasErrors }))
  }

  const rowCount = Math.max(
    1,
    layout.reduce((max, item) => Math.max(max, item.y + item.h), 0),
  )

  return (
    <div className="od-dash">
      <AdminPageActions label={layoutLabel} slot="page">
        <AddWidgetMenu
          hidden={hidden.filter((id) => widgets[id])}
          labelFor={labelFor}
          onAdd={addWidget}
          open={addOpen}
          onToggle={() => setAddOpen((open) => !open)}
        />
        <button type="button" className="od-cbtn" onClick={resetLayout}>
          Reset layout
        </button>
      </AdminPageActions>
      {onRefresh ? (
        <AdminPageActions label={statusLabel} slot="trail">
          <span className="od-ops-refresh-wrap">
            <button
              type="button"
              className="od-ops-refresh-icon"
              aria-label={refreshing ? 'Refreshing' : refreshAriaLabel}
              aria-describedby={asOf ? asOfId : undefined}
              title={asOf ? `Updated ${new Date(asOf).toLocaleString()}` : 'Refresh'}
              onClick={onRefresh}
              disabled={refreshDisabled || refreshing}
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5"
                />
              </svg>
            </button>
            {asOf ? (
              <span id={asOfId} className="od-ops-refresh-asof" role="tooltip">
                Updated {new Date(asOf).toLocaleString()}
              </span>
            ) : null}
          </span>
        </AdminPageActions>
      ) : null}

      <div
        ref={boardRef}
        className="od-dash__board"
        aria-label={boardAriaLabel || undefined}
        style={{
          gridTemplateRows: `repeat(${rowCount}, var(--od-dash-row))`,
        }}
      >
        {layout.map((item) => {
          const body = widgets[item.id]
          if (!body || hidden.includes(item.id)) return null
          const isPinned = pinned.includes(item.id)
          const busy = activeId === item.id
          const movePreview =
            busy && preview?.mode === 'move' && preview.id === item.id ? preview : null
          const resizePreview =
            busy && preview?.mode === 'resize' && preview.id === item.id ? preview : null
          return (
            <div
              key={item.id}
              className={`od-dash__item${busy ? ' is-dragging' : ''}${isPinned ? ' is-pinned' : ''}`}
              style={{
                gridColumn: `${item.x + 1} / span ${item.w}`,
                gridRow: `${item.y + 1} / span ${item.h}`,
                ...(movePreview
                  ? {
                      transform: `translate(${movePreview.dx}px, ${movePreview.dy}px)`,
                      zIndex: 5,
                    }
                  : null),
              }}
              data-widget={item.id}
              data-fit={item.id === 'status' || item.id.startsWith('m-') ? 'true' : undefined}
              role="group"
              tabIndex={0}
              aria-label={`${labelFor(item.id)}${isPinned ? ' (pinned)' : ''}. Arrow keys move, shift and arrow keys resize.`}
              onKeyDown={(event) => onItemKeyDown(item.id, event)}
              onPointerDown={(event) => beginMove(item.id, event)}
            >
              <div className="od-dash__body">{body}</div>
              {resizePreview ? (
                <div
                  className="od-dash__resize-ghost"
                  aria-hidden="true"
                  style={{
                    width: `calc(100% * ${Math.max(1, resizePreview.w)} / ${item.w})`,
                    height: `calc(100% * ${Math.max(1, resizePreview.h)} / ${item.h})`,
                  }}
                />
              ) : null}
              <WidgetChrome
                label={labelFor(item.id)}
                pinned={isPinned}
                onTogglePin={() => prefs.togglePin(item.id)}
                onPreset={(preset: SizePreset) =>
                  setLayout((prev) => applySizePreset(prev, item.id, preset, minsFn, pinned))
                }
                onHide={() => hideWidget(item.id)}
              />
              {isPinned ? null : (
                <>
                  <button
                    type="button"
                    className="od-dash__resize od-dash__resize--x"
                    aria-label={`Resize ${labelFor(item.id)} width`}
                    title="Drag to change width"
                    onPointerDown={(event) => beginResize(item.id, event, 'x')}
                  />
                  <button
                    type="button"
                    className="od-dash__resize od-dash__resize--y"
                    aria-label={`Resize ${labelFor(item.id)} height`}
                    title="Drag to change height"
                    onPointerDown={(event) => beginResize(item.id, event, 'y')}
                  />
                  <button
                    type="button"
                    className="od-dash__resize"
                    aria-label={`Resize ${labelFor(item.id)}`}
                    title="Drag corner to resize"
                    onPointerDown={(event) => beginResize(item.id, event)}
                  />
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
