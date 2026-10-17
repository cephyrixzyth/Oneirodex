import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { useRowScroll } from './useRowScroll'

describe('useRowScroll wheel', () => {
  let track: any
  let viewport: any
  let page: any

  beforeEach(() => {
    track = document.createElement('div')
    viewport = document.createElement('div')
    page = document.createElement('div')
    Object.defineProperty(track, 'clientWidth', { configurable: true, value: 400 })
    Object.defineProperty(track, 'scrollWidth', { configurable: true, value: 1200 })
    Object.defineProperty(page, 'clientHeight', { configurable: true, value: 400 })
    Object.defineProperty(page, 'scrollHeight', { configurable: true, value: 2000 })
    page.style.overflowY = 'auto'
    page.scrollTop = 0
    track.scrollLeft = 0
    page.append(viewport)
    viewport.append(track)
    document.body.append(page)
  })

  afterEach(() => {
    page.remove()
  })

  test('vertical wheel over the viewport scrolls the page, not the track', () => {
    renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      scroll.viewportRef.current = viewport
      return scroll
    })

    const blocked: any = !viewport.dispatchEvent(
      new WheelEvent('wheel', { deltaY: 80, deltaMode: 0, bubbles: true, cancelable: true }),
    )
    expect(blocked).toBe(true)
    expect(track.scrollLeft).toBe(0)
    expect(page.scrollTop).toBe(80)
  })

  test('horizontal-dominant wheel over tiles pans the track both ways', () => {
    renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      scroll.viewportRef.current = viewport
      return scroll
    })

    track.scrollLeft = 120
    const blockedBack: any = !viewport.dispatchEvent(
      new WheelEvent('wheel', {
        deltaX: -50,
        deltaY: 8,
        deltaMode: 0,
        bubbles: true,
        cancelable: true,
      }),
    )
    expect(blockedBack).toBe(true)
    expect(track.scrollLeft).toBe(70)
    expect(page.scrollTop).toBe(0)

    const blockedForward: any = !viewport.dispatchEvent(
      new WheelEvent('wheel', {
        deltaX: 40,
        deltaY: 5,
        deltaMode: 0,
        bubbles: true,
        cancelable: true,
      }),
    )
    expect(blockedForward).toBe(true)
    expect(track.scrollLeft).toBe(110)
    expect(page.scrollTop).toBe(0)
  })

  test('shift-wheel over tiles pans the track backward', () => {
    renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      scroll.viewportRef.current = viewport
      return scroll
    })

    track.scrollLeft = 90
    const blocked: any = !viewport.dispatchEvent(
      new WheelEvent('wheel', {
        deltaY: -40,
        shiftKey: true,
        deltaMode: 0,
        bubbles: true,
        cancelable: true,
      }),
    )
    expect(blocked).toBe(true)
    expect(track.scrollLeft).toBe(50)
    expect(page.scrollTop).toBe(0)
  })

  test('wheel over the track itself scrolls the page, not the track', () => {
    renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      scroll.viewportRef.current = viewport
      return scroll
    })

    const blocked: any = !track.dispatchEvent(
      new WheelEvent('wheel', { deltaY: 40, deltaMode: 0, bubbles: true, cancelable: true }),
    )
    expect(blocked).toBe(true)
    expect(track.scrollLeft).toBe(0)
    expect(page.scrollTop).toBe(40)
  })

  test('wheel over the slider pans the track', () => {
    const hbar = document.createElement('div')
    viewport.append(hbar)
    hbar.getBoundingClientRect = (): DOMRect =>
      ({
        left: 0,
        right: 400,
        top: 200,
        bottom: 208,
        width: 400,
        height: 8,
      }) as DOMRect

    renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      scroll.viewportRef.current = viewport
      scroll.hbarRef.current = hbar
      return scroll
    })

    const blocked = !hbar.dispatchEvent(
      new WheelEvent('wheel', {
        deltaY: 50,
        deltaMode: 0,
        bubbles: true,
        cancelable: true,
        clientX: 40,
        clientY: 204,
      }),
    )
    expect(blocked).toBe(true)
    expect(track.scrollLeft).toBe(50)
    expect(page.scrollTop).toBe(0)
  })

  test('wheel over the slider pans the track backward', () => {
    const hbar = document.createElement('div')
    viewport.append(hbar)
    hbar.getBoundingClientRect = (): DOMRect =>
      ({
        left: 0,
        right: 400,
        top: 200,
        bottom: 208,
        width: 400,
        height: 8,
      }) as DOMRect

    renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      scroll.viewportRef.current = viewport
      scroll.hbarRef.current = hbar
      return scroll
    })

    track.scrollLeft = 80
    const blocked = !hbar.dispatchEvent(
      new WheelEvent('wheel', {
        deltaY: -30,
        deltaMode: 0,
        bubbles: true,
        cancelable: true,
        clientX: 40,
        clientY: 204,
      }),
    )
    expect(blocked).toBe(true)
    expect(track.scrollLeft).toBe(50)
    expect(page.scrollTop).toBe(0)
  })

  test('wheel over the track padding that covers the slider still pans', () => {
    const hbar = document.createElement('div')
    viewport.append(hbar)
    hbar.getBoundingClientRect = (): DOMRect =>
      ({
        left: 0,
        right: 400,
        top: 200,
        bottom: 208,
        width: 400,
        height: 8,
      }) as DOMRect

    renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      scroll.viewportRef.current = viewport
      scroll.hbarRef.current = hbar
      return scroll
    })

    // Target is the track (old stacking bug), but the pointer is on the bar.
    const blocked: any = !track.dispatchEvent(
      new WheelEvent('wheel', {
        deltaY: 40,
        deltaMode: 0,
        bubbles: true,
        cancelable: true,
        clientX: 40,
        clientY: 204,
      }),
    )
    expect(blocked).toBe(true)
    expect(track.scrollLeft).toBe(40)
    expect(page.scrollTop).toBe(0)
  })
})

describe('useRowScroll arrow hover', () => {
  let track: any
  let queued: any
  let frameId: any

  beforeEach(() => {
    track = document.createElement('div')
    Object.defineProperty(track, 'clientWidth', { configurable: true, value: 400 })
    Object.defineProperty(track, 'scrollWidth', { configurable: true, value: 1200 })
    track.scrollLeft = 0
    track.scrollBy = ({ left = 0 } = {}) => {
      track.scrollLeft += left
    }
    document.body.append(track)
    queued = null
    frameId = 0
    vi.stubGlobal('requestAnimationFrame', (cb: any) => {
      queued = cb
      frameId += 1
      return frameId
    })
    vi.stubGlobal('cancelAnimationFrame', () => {
      queued = null
    })
  })

  afterEach(() => {
    track.remove()
    vi.unstubAllGlobals()
  })

  test('hovering an arrow eases the track along', () => {
    const { result } = renderHook(() => useRowScroll({ edgeSpeed: 10 }))
    result.current.ref.current = track
    result.current.startEdgeScroll(1)
    queued?.(0)
    expect(track.scrollLeft).toBe(10)
  })

  test('a click before the first hover frame pages and cancels the pending loop', () => {
    const { result } = renderHook(() => useRowScroll({ edgeSpeed: 10 }))
    result.current.ref.current = track
    result.current.startEdgeScroll(1)
    expect(queued).toBeTruthy()
    act(() => result.current.scrollByPage(1))
    expect(queued).toBeNull()
    expect(track.scrollLeft).toBeCloseTo(220)
  })

  test('a native scroll event turns the start arrow on', async () => {
    const { result }: any = renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      return scroll
    })

    expect(result.current.overflow.start).toBe(false)
    await act(async () => {
      track.scrollLeft = 80
      track.dispatchEvent(new Event('scroll'))
    })
    expect(result.current.overflow.start).toBe(true)
  })

  test('a click while hover-scrolling does not page-jump', () => {
    const { result } = renderHook(() => useRowScroll({ edgeSpeed: 10, step: 0.85 }))
    result.current.ref.current = track
    result.current.startEdgeScroll(1)
    queued?.(0)
    expect(track.scrollLeft).toBe(10)
    result.current.scrollByPage(1)
    expect(track.scrollLeft).toBe(10)
  })

  test('Discover can wrap left from the first tile to the last', () => {
    const { result } = renderHook(() => useRowScroll({ wrapAround: true }))
    result.current.ref.current = track

    act(() => result.current.scrollByPage(-1))

    expect(track.scrollLeft).toBe(800)
  })

  test('Discover can wrap right from the last tile to the first', () => {
    const { result } = renderHook(() => useRowScroll({ wrapAround: true }))
    result.current.ref.current = track
    track.scrollLeft = 800

    act(() => result.current.scrollByPage(1))

    expect(track.scrollLeft).toBe(0)
  })
})

describe('useRowScroll grab-to-scroll', () => {
  let track: any
  let viewport: any

  function pointer(type: any, init: any) {
    // jsdom has no PointerEvent constructor; a MouseEvent with the pointer
    // fields assigned is what the hook reads.
    // button / clientX are MouseEvent getters and go through the constructor;
    // the pointer-only fields are plain properties the hook reads.
    const { pointerId = 1, pointerType = 'mouse', ...mouse } = init
    const event = new MouseEvent(type, { bubbles: true, cancelable: true, ...mouse })
    Object.defineProperty(event, 'pointerId', { value: pointerId })
    Object.defineProperty(event, 'pointerType', { value: pointerType })
    return event
  }

  beforeEach(() => {
    track = document.createElement('div')
    viewport = document.createElement('div')
    Object.defineProperty(track, 'clientWidth', { configurable: true, value: 400 })
    Object.defineProperty(track, 'scrollWidth', { configurable: true, value: 1200 })
    track.scrollLeft = 0
    track.setPointerCapture = vi.fn()
    track.releasePointerCapture = vi.fn()
    viewport.append(track)
    document.body.append(viewport)
    renderHook(() => {
      const scroll = useRowScroll({ bindKey: 1 })
      scroll.ref.current = track
      scroll.viewportRef.current = viewport
      return scroll
    })
  })

  afterEach(() => {
    viewport.remove()
  })

  test('a mouse drag from the first tile pans the track and swallows the click', () => {
    const tile = document.createElement('div')
    track.append(tile)
    const opened = vi.fn()
    tile.addEventListener('click', opened)

    tile.dispatchEvent(pointer('pointerdown', { button: 0, clientX: 300 }))
    tile.dispatchEvent(pointer('pointermove', { clientX: 100 }))
    expect(track.scrollLeft).toBe(200)
    expect(track.dataset.dragging).toBe('true')

    tile.dispatchEvent(pointer('pointerup', { clientX: 100 }))
    expect(track.dataset.dragging).toBeUndefined()

    tile.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(opened).not.toHaveBeenCalled()
  })

  test('a press that does not move is still a click', () => {
    const tile = document.createElement('div')
    track.append(tile)
    const opened = vi.fn()
    tile.addEventListener('click', opened)

    tile.dispatchEvent(pointer('pointerdown', { button: 0, clientX: 300 }))
    tile.dispatchEvent(pointer('pointermove', { clientX: 302 }))
    tile.dispatchEvent(pointer('pointerup', { clientX: 302 }))
    expect(track.scrollLeft).toBe(0)

    tile.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(opened).toHaveBeenCalledTimes(1)
  })

  test('a press on a control inside the track does not start a drag', () => {
    const button = document.createElement('button')
    track.append(button)
    button.dispatchEvent(pointer('pointerdown', { button: 0, clientX: 300 }))
    button.dispatchEvent(pointer('pointermove', { clientX: 100 }))
    expect(track.scrollLeft).toBe(0)
  })
})
