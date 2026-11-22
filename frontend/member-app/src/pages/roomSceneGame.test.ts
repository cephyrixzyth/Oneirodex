import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRoom } from './roomScene'

const mock = vi.hoisted(() => ({
  loop: null as ((time: number) => void) | null,
  scene: null as import('three').Scene | null,
  render: vi.fn(),
  dispose: vi.fn(),
  controllers: [] as import('three').Group[],
}))
vi.mock('three', async () => {
  const actual = await vi.importActual<typeof import('three')>('three')
  class Renderer {
    shadowMap = { enabled: false, type: 0 }
    xr = {
      enabled: false,
      isPresenting: false,
      setReferenceSpaceType: vi.fn(),
      getController: (index: number) => mock.controllers[index],
      setSession: async (session: EventTarget) => {
        this.xr.isPresenting = true
        session.addEventListener('end', () => {
          this.xr.isPresenting = false
        })
      },
    }
    constructor() {
      mock.controllers = [new actual.Group(), new actual.Group()]
    }
    setPixelRatio() {}
    setSize() {}
    render(scene: import('three').Scene, camera: import('three').Camera) {
      scene.updateMatrixWorld(true)
      camera.updateMatrixWorld(true)
      mock.scene = scene
      mock.render()
    }
    setAnimationLoop(loop: ((time: number) => void) | null) {
      mock.loop = loop
    }
    dispose() {
      mock.dispose()
    }
    forceContextLoss() {}
  }
  return { ...actual, WebGLRenderer: Renderer }
})

let root: HTMLElement, canvas: HTMLCanvasElement
const cleanup: (() => void)[] = []
beforeEach(() => {
  vi.clearAllMocks()
  mock.loop = null
  mock.scene = null
  root = document.createElement('section')
  root.className = 'od-library-room'
  canvas = document.createElement('canvas')
  canvas.tabIndex = 0
  canvas.setPointerCapture = vi.fn()
  root.append(canvas)
  document.body.append(root)
  canvas.focus()
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
    width: 1000,
    height: 700,
    top: 0,
    left: 0,
    right: 1000,
    bottom: 700,
    x: 0,
    y: 0,
    toJSON() {},
  })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    fillRect: vi.fn(),
    fillText: vi.fn(),
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    measureText: (text: string) => ({ width: text.length * 12 }),
  } as never)
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
})
afterEach(() => {
  cleanup.splice(0).forEach((fn) => fn())
  root.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
const view = {
  favoriteMessage: '',
  collection: false,
  games: [],
  selected: null,
  detailMessage: '',
  shelf: 'No titles',
  previous: false,
  next: false,
}

describe('scene and pinball integration with a fake renderer (no app or GPU)', () => {
  it('constructs the actual observatory and advances the real model from the scene clock', () => {
    const engine = createRoom(canvas, vi.fn(), vi.fn(), vi.fn(), { theme: 'default' })
    cleanup.push(engine.dispose)
    engine.update(view)
    expect(mock.scene?.getObjectByName('observatory-dome')).toBeDefined()
    expect(mock.scene?.getObjectByName('moonfall-pinball-table')).toBeDefined()
    expect(engine.game).toBeTruthy()
    engine.game!.start()
    engine.game!.input('launch', true, 'test')
    mock.loop!(1000)
    mock.loop!(1020)
    expect(engine.game!.snapshot().phase).toBe('playing')
    expect(engine.game!.snapshot().tick).toBeGreaterThan(0)
    engine.move('library')
    expect(engine.game!.status()).toBe('paused')
  })

  it('does not advertise a new game on the seven legacy rooms', () => {
    const engine = createRoom(canvas, vi.fn(), vi.fn(), vi.fn(), { theme: 'greenhouse' })
    cleanup.push(engine.dispose)
    expect(engine.game).toBeNull()
    expect(mock.scene?.getObjectByName('observatory-dome')).toBeUndefined()
  })

  it('pauses on context loss and refuses a blind resume until the room is reopened', () => {
    const problem = vi.fn()
    const engine = createRoom(canvas, vi.fn(), vi.fn(), problem, { theme: 'default' })
    cleanup.push(engine.dispose)
    engine.game!.start()
    canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true }))
    expect(engine.game!.status()).toBe('paused')
    engine.game!.resume()
    expect(engine.game!.status()).toBe('paused')
    expect(problem).toHaveBeenCalled()
  })

  it('disposes its clock, scene and private model without later callback emissions', () => {
    const changed = vi.fn()
    const engine = createRoom(canvas, vi.fn(), vi.fn(), vi.fn(), {
      theme: 'default',
      onGameSnapshot: changed,
    })
    engine.game!.start()
    engine.dispose()
    const count = changed.mock.calls.length
    window.dispatchEvent(new Event('blur'))
    expect(mock.loop).toBeNull()
    expect(mock.dispose).toHaveBeenCalledOnce()
    expect(engine.game!.status()).toBe('disposed')
    expect(changed).toHaveBeenCalledTimes(count)
  })

  it('clears private progress and prevents further play after access is denied', () => {
    const engine = createRoom(canvas, vi.fn(), vi.fn(), vi.fn(), { theme: 'default' })
    cleanup.push(engine.dispose)
    engine.game!.start()
    engine.game!.deny()
    engine.game!.start()
    engine.game!.resume()
    expect(engine.game!.status()).toBe('disposed')
    expect(engine.game!.snapshot().best).toBe(0)
  })

  it('routes XR triggers to flippers and pauses when the headset session loses visibility', async () => {
    class Session extends EventTarget {
      visibilityState = 'visible'
      inputSources = []
      async end() {
        this.dispatchEvent(new Event('end'))
      }
    }
    const session = new Session()
    vi.stubGlobal('navigator', { xr: { requestSession: async () => session } })
    const engine = createRoom(canvas, vi.fn(), vi.fn(), vi.fn(), { theme: 'default' })
    cleanup.push(engine.dispose)
    engine.game!.start()
    await engine.enter()
    engine.game!.resume()
    const controller = mock.controllers[0] as unknown as {
      dispatchEvent(event: { type: string }): void
    }
    controller.dispatchEvent({ type: 'selectstart' })
    mock.loop!(1000)
    mock.loop!(1100)
    expect(engine.game!.snapshot().flippers.left).toBeCloseTo(-0.72)
    controller.dispatchEvent({ type: 'selectend' })
    mock.loop!(1200)
    expect(engine.game!.snapshot().flippers.left).toBeCloseTo(0.24)
    session.visibilityState = 'visible-blurred'
    session.dispatchEvent(new Event('visibilitychange'))
    expect(engine.game!.status()).toBe('paused')
    session.visibilityState = 'visible'
    session.dispatchEvent(new Event('visibilitychange'))
    expect(engine.game!.status()).toBe('paused')
  })

  it('supports chorded mouse flippers and releases them on pointer cancellation', () => {
    const engine = createRoom(canvas, vi.fn(), vi.fn(), vi.fn(), { theme: 'default' })
    cleanup.push(engine.dispose)
    engine.game!.start()
    const pointer = (type: string, buttons: number) => {
      const event = new MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        clientX: 500,
        clientY: 350,
        button: 0,
        buttons,
      })
      Object.defineProperties(event, { pointerId: { value: 1 }, pointerType: { value: 'mouse' } })
      canvas.dispatchEvent(event)
    }
    pointer('pointerdown', 1)
    mock.loop!(1000)
    mock.loop!(1100)
    expect(engine.game!.snapshot().flippers.left).toBeCloseTo(-0.72)
    pointer('pointermove', 3)
    mock.loop!(1200)
    expect(engine.game!.snapshot().flippers.right).toBeCloseTo(Math.PI + 0.72)
    pointer('pointercancel', 0)
    mock.loop!(1300)
    expect(engine.game!.snapshot().flippers.left).toBeCloseTo(0.24)
    expect(engine.game!.snapshot().flippers.right).toBeCloseTo(Math.PI - 0.24)
  })
})

it.each(['Standard', 'Seated', 'Close reach'] as const)(
  'keeps score and playfield visible in %s at desktop and narrow widths',
  async (comfort) => {
    const THREE = await import('three')
    for (const width of [1000, 400]) {
      vi.mocked(canvas.getBoundingClientRect).mockReturnValue({
        ...canvas.getBoundingClientRect(),
        width,
      })
      const room = createRoom(canvas, vi.fn(), vi.fn(), vi.fn())
      cleanup.push(room.dispose)
      room.update({
        comfort,
        largeText: false,
        collection: true,
        favoriteMessage: '',
        games: [],
        selected: null,
        detailMessage: '',
        shelf: 'test',
        previous: false,
        next: false,
      })
      room.game!.start()
      const camera = mock.scene!.getObjectByProperty(
        'type',
        'PerspectiveCamera',
      ) as import('three').PerspectiveCamera
      for (const point of [
        new THREE.Vector3(-0.64, 1.83, -1.54),
        new THREE.Vector3(0.64, 1.61, -1.54),
        new THREE.Vector3(-0.7, 0.98, 1.48),
        new THREE.Vector3(0.7, 0.98, 1.48),
      ]) {
        const projected = point.project(camera)
        expect(Math.abs(projected.x)).toBeLessThan(0.98)
        expect(Math.abs(projected.y)).toBeLessThan(0.98)
      }
      room.dispose()
    }
  },
)
