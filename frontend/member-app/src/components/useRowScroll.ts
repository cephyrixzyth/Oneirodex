import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

/**
 * Horizontal scrolling for a shelf.
 *
 * Vertical wheel over the tiles or the row title scrolls the page.
 * Horizontal wheel, shift-wheel, and wheel over the bottom slider pan the
 * track in both directions. Hover arrows still page/hold.
 *
 * @param {object} [options]
 * @param {number} [options.step] Fraction of the visible width one arrow press
 *   moves when the hover loop is not already running. Half a page keeps a tile
 *   on screen as an anchor without leaping past a whole row.
 * @param {number} [options.edgeSpeed] Pixels per animation frame while hovering
 *   an arrow. ~150px/s at 60fps — slow enough to read covers as they pass.
 * @param {unknown} [options.bindKey] Change this when the track node mounts or
 *   is replaced so the non-passive wheel listener rebinds (refs alone do not
 *   re-run an effect).
 */
export function useRowScroll({ step = 0.55, edgeSpeed = 2.5, bindKey = 0, wrapAround = false }: LooseProps = {}) {
  const ref = useRef<any>(null)
  /** Outer hover zone (viewport / scroller). Wheel binds here so the lane under
   *  the custom scrollbar and the arrow fades do not become accidental row scroll. */
  const viewportRef = useRef<any>(null)
  /** Custom horizontal scrollbar — wheel here pans the track. */
  const hbarRef = useRef<any>(null)
  const frameRef = useRef(0)
  const directionRef = useRef(0)
  const edgeMovedRef = useRef(false)
  const [overflow, setOverflow] = useState({ start: false, end: false })

  /** Whether there is anything left to scroll to, in each direction. */
  const measure = useCallback(() => {
    const node = ref.current
    if (!node) return
    // 1px of slack: fractional layout widths mean scrollLeft never quite
    // reaches the arithmetic maximum, which would leave the end arrow enabled
    // forever on a fully-scrolled row.
    const max = node.scrollWidth - node.clientWidth
    setOverflow({ start: node.scrollLeft > 1, end: node.scrollLeft < max - 1 })
  }, [])

  useEffect(() => {
    const node = ref.current
    if (!node) return undefined
    measure()

    // Tiles arrive after the row does — the shelf fills itself in as it is
    // scrolled — so the arrows have to re-evaluate when the content grows, not
    // only when the window resizes.
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(node)
    for (const child of node.children) observer?.observe(child)

    window.addEventListener('resize', measure)
    const onScroll = () => measure()
    node.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', measure)
      node.removeEventListener('scroll', onScroll)
    }
  }, [measure, bindKey])

  const stopEdgeScroll = useCallback(() => {
    directionRef.current = 0
    edgeMovedRef.current = false
    if (frameRef.current) {
      cancelAnimationFrame(frameRef.current)
      frameRef.current = 0
    }
  }, [])

  // Stop the moment the component goes away, or the loop outlives the row.
  useEffect(() => stopEdgeScroll, [stopEdgeScroll])

  const startEdgeScroll = useCallback(
    (direction: any) => {
      if (directionRef.current === direction) return
      directionRef.current = direction
      edgeMovedRef.current = false
      if (frameRef.current) return

      const tick = () => {
        const node = ref.current
        if (!node || !directionRef.current) {
          frameRef.current = 0
          return
        }
        const max = node.scrollWidth - node.clientWidth
        const previousLeft = node.scrollLeft
        node.scrollLeft = Math.max(
          0,
          Math.min(max, node.scrollLeft + directionRef.current * edgeSpeed),
        )
        if (node.scrollLeft !== previousLeft) edgeMovedRef.current = true
        measure()
        if (node.scrollLeft <= 0 || node.scrollLeft >= max - 1) {
          directionRef.current = 0
          frameRef.current = 0
          return
        }
        frameRef.current = requestAnimationFrame(tick)
      }
      frameRef.current = requestAnimationFrame(tick)
    },
    [edgeSpeed, measure],
  )

  /** Arrow press: one near-page, animated unless the member asked for less.
   *  A click while the hover loop is already running must not also page-jump —
   *  that was the bumper that skipped instead of easing. */
  const scrollByPage = useCallback(
    (direction: any) => {
      // A quick click/tap can arrive before the first hover frame has moved.
      const wasHovering = directionRef.current !== 0 && edgeMovedRef.current
      stopEdgeScroll()
      if (wasHovering) return
      const node = ref.current
      if (!node) return
      const reduced =
        typeof window !== 'undefined' &&
        window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      const max = Math.max(0, node.scrollWidth - node.clientWidth)
      const atStart = node.scrollLeft <= 1
      const atEnd = node.scrollLeft >= max - 1
      if (wrapAround && max > 1 && ((direction < 0 && atStart) || (direction > 0 && atEnd))) {
        const target = direction < 0 ? max : 0
        node.scrollBy({
          left: target - node.scrollLeft,
          behavior: reduced ? 'auto' : 'smooth',
        })
        measure()
        return
      }
      node.scrollBy({
        left: direction * node.clientWidth * step,
        behavior: reduced ? 'auto' : 'smooth',
      })
      measure()
    },
    [measure, step, stopEdgeScroll, wrapAround],
  )

  const wheelDeltaPx = useCallback((event: any, fallbackPage: any) => {
    let delta =
      event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)
        ? event.deltaX || event.deltaY
        : event.deltaY
    if (event.deltaMode === 1) delta *= 16
    else if (event.deltaMode === 2) {
      delta *= typeof window !== 'undefined' ? window.innerHeight * 0.85 : fallbackPage
    }
    return delta
  }, [])

  /** Wheel over the bottom slider pans the shelf track. */
  const panTrackByWheel = useCallback(
    (event: any) => {
      const node = ref.current
      if (!node) return false
      if (node.scrollWidth <= node.clientWidth + 1) return false

      event.preventDefault()
      event.stopPropagation()

      const delta = wheelDeltaPx(event, node.clientWidth * step)
      const max = node.scrollWidth - node.clientWidth
      node.scrollLeft = Math.max(0, Math.min(max, node.scrollLeft + delta))
      measure()
      return true
    },
    [measure, step, wheelDeltaPx],
  )

  const wheelOverHbar = useCallback((event: any) => {
    const bar = hbarRef.current
    if (!bar) return false
    if (bar === event.target || bar.contains(event.target)) return true
    // Geometry fallback: the track's bottom padding used to paint above the
    // bar (higher z-index) so the event target was the track, not the rail.
    const pad = 8
    const box = bar.getBoundingClientRect()
    return (
      event.clientX >= box.left &&
      event.clientX <= box.right &&
      event.clientY >= box.top - pad &&
      event.clientY <= box.bottom + pad
    )
  }, [])

  /**
   * Vertical wheel over tiles / title scrolls the page. Horizontal wheel,
   * shift-wheel, and wheel on the slider pan the track both ways. Capture on
   * the scroller so the track padding cannot steal the bar.
   */
  const onWheel = useCallback(
    (event: any) => {
      const node = ref.current
      if (!node) return

      if (wheelOverHbar(event)) {
        panTrackByWheel(event)
        return
      }

      if (node.scrollWidth <= node.clientWidth + 1) return

      const vertical = !event.shiftKey && Math.abs(event.deltaY) >= Math.abs(event.deltaX)
      if (!vertical) {
        panTrackByWheel(event)
        return
      }

      event.preventDefault()
      event.stopPropagation()

      const delta = wheelDeltaPx(
        event,
        typeof window !== 'undefined' ? window.innerHeight * 0.85 : node.clientWidth * step,
      )

      let target = node.parentElement
      while (target && target !== document.documentElement) {
        const style = window.getComputedStyle(target)
        const oy = style.overflowY
        if (
          (oy === 'auto' || oy === 'scroll' || oy === 'overlay') &&
          target.scrollHeight > target.clientHeight + 1
        ) {
          target.scrollTop += delta
          return
        }
        target = target.parentElement
      }
      window.scrollBy(0, delta)
    },
    [panTrackByWheel, step, wheelDeltaPx, wheelOverHbar],
  )

  // React attaches wheel handlers passively, so `preventDefault()` inside an
  // onWheel prop is ignored. Bind on the scroller (viewportRef) in capture.
  // bindKey re-runs when the shelf mounts its track after a null first paint.
  useLayoutEffect(() => {
    const scroller = viewportRef.current
    const track = ref.current
    const nodes = [...new Set([scroller, track].filter(Boolean))]
    if (!nodes.length) return undefined
    for (const listenNode of nodes) {
      listenNode.addEventListener('wheel', onWheel, { passive: false, capture: true })
    }
    return () => {
      for (const listenNode of nodes) {
        listenNode.removeEventListener('wheel', onWheel, { capture: true })
      }
    }
  }, [onWheel, bindKey])

  // Grab-to-scroll with a mouse. Arrows page half a screen and the wheel pans
  // a notch at a time, so reaching the far end of a long row from its first
  // tile was a lot of input (human, 2026-09-06: "all rows should be scrollable
  // left/right even the first tile so you get to the end tile quicker"). A
  // press anywhere on the track — first tile included — drags the row; the
  // click that would have opened the tile is swallowed only if the pointer
  // actually moved. Touch already scrolls natively and is left alone.
  useLayoutEffect(() => {
    const track = ref.current
    if (!track) return undefined
    const DRAG_THRESHOLD_PX = 6
    let pointerId: number | null = null
    let startX = 0
    let startScroll = 0
    let dragged = false

    const swallowClick = (event: Event) => {
      event.stopPropagation()
      event.preventDefault()
    }

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse' || event.button !== 0) return
      // Controls on the track (Pin / Hide / See all, the play button) keep
      // their own press; only art and empty track start a drag.
      const target = event.target as HTMLElement | null
      // Tile art is usually itself a link. It remains a click when the pointer
      // stays put; after the drag threshold the existing click guard swallows
      // navigation, allowing a row to be dragged from its first cover.
      if (target && target.closest('button, input, select, textarea')) return
      pointerId = event.pointerId
      startX = event.clientX
      startScroll = track.scrollLeft
      dragged = false
    }

    const onPointerMove = (event: PointerEvent) => {
      if (pointerId === null || event.pointerId !== pointerId) return
      const dx = event.clientX - startX
      if (!dragged) {
        if (Math.abs(dx) < DRAG_THRESHOLD_PX) return
        dragged = true
        try {
          track.setPointerCapture(pointerId)
        } catch {
          /* capture is a nicety; the listeners are on the track anyway */
        }
        track.dataset.dragging = 'true'
        // One-shot: the click after a drag is not a tile activation.
        track.addEventListener('click', swallowClick, { capture: true, once: true })
      }
      track.scrollLeft = startScroll - dx
      measure()
      event.preventDefault()
    }

    const onPointerEnd = (event: PointerEvent) => {
      if (pointerId === null || event.pointerId !== pointerId) return
      if (dragged) {
        try {
          track.releasePointerCapture(pointerId)
        } catch {
          /* already released */
        }
        delete track.dataset.dragging
      } else {
        // Never moved: make sure a stale swallow listener cannot linger.
        track.removeEventListener('click', swallowClick, { capture: true })
      }
      pointerId = null
      dragged = false
    }

    track.addEventListener('pointerdown', onPointerDown)
    track.addEventListener('pointermove', onPointerMove)
    track.addEventListener('pointerup', onPointerEnd)
    track.addEventListener('pointercancel', onPointerEnd)
    return () => {
      track.removeEventListener('pointerdown', onPointerDown)
      track.removeEventListener('pointermove', onPointerMove)
      track.removeEventListener('pointerup', onPointerEnd)
      track.removeEventListener('pointercancel', onPointerEnd)
      track.removeEventListener('click', swallowClick, { capture: true })
    }
  }, [measure, bindKey])

  return {
    ref,
    viewportRef,
    hbarRef,
    overflow,
    measure,
    scrollByPage,
    /** Hover the left/right arrow controls — continuous scroll while held. */
    startEdgeScroll,
    stopEdgeScroll,
  }
}
