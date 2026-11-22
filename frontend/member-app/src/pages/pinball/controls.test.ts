import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinballRuntime } from './runtime'
import { bindPinballControls } from './controls'

let root: HTMLElement, canvas: HTMLCanvasElement
const cleanups: (() => void)[] = []
beforeEach(() => {
  root = document.createElement('section')
  root.className = 'od-library-room'
  canvas = document.createElement('canvas')
  canvas.tabIndex = 0
  root.append(canvas)
  document.body.append(root)
  canvas.focus()
})
afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup())
  root.remove()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
const key = (type: 'keydown' | 'keyup', code: string, target: EventTarget = canvas) =>
  target.dispatchEvent(new KeyboardEvent(type, { code, bubbles: true, cancelable: true }))

describe('pinball input ownership and focus', () => {
  it('accepts keyboard launch and releases flippers after a keyup outside the room', () => {
    const runtime = createPinballRuntime()
    const controls = bindPinballControls(canvas, runtime)
    cleanups.push(controls.dispose)
    runtime.start()
    key('keydown', 'Space')
    key('keyup', 'Space', window)
    runtime.tick(1 / 120)
    expect(runtime.snapshot().phase).toBe('playing')
    key('keydown', 'KeyZ')
    runtime.tick(0.1)
    expect(runtime.snapshot().flippers.left).toBeCloseTo(-0.72)
    key('keyup', 'KeyZ', window)
    runtime.tick(0.1)
    expect(runtime.snapshot().flippers.left).toBeCloseTo(0.24)
  })

  it('does not steal keystrokes from text inputs or the ordinary library', () => {
    const runtime = createPinballRuntime()
    const controls = bindPinballControls(canvas, runtime)
    cleanups.push(controls.dispose)
    runtime.start()
    const input = document.createElement('input')
    root.append(input)
    input.focus()
    key('keydown', 'Space', input)
    key('keydown', 'KeyZ', document.body)
    runtime.tick(1 / 120)
    expect(runtime.snapshot().phase).toBe('ready')
    expect(runtime.snapshot().flippers.left).toBeCloseTo(0.24)
  })

  it('pauses on blur and on explicit Escape without automatic focus resume', () => {
    const runtime = createPinballRuntime()
    const controls = bindPinballControls(canvas, runtime)
    cleanups.push(controls.dispose)
    runtime.start()
    window.dispatchEvent(new Event('blur'))
    window.dispatchEvent(new Event('focus'))
    expect(runtime.status()).toBe('paused')
    runtime.resume()
    key('keydown', 'Escape')
    expect(runtime.status()).toBe('paused')
  })

  it('pauses on hidden desktop context while leaving XR focus to the XR session handler', () => {
    const runtime = createPinballRuntime()
    let immersive = false
    const controls = bindPinballControls(canvas, runtime, () => immersive)
    cleanups.push(controls.dispose)
    runtime.start()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    expect(runtime.status()).toBe('paused')
    runtime.resume()
    immersive = true
    window.dispatchEvent(new Event('blur'))
    expect(runtime.status()).toBe('running')
  })

  it('combines gamepad and keyboard inputs and requires a new Start press to resume', () => {
    const runtime = createPinballRuntime()
    const controls = bindPinballControls(canvas, runtime)
    cleanups.push(controls.dispose)
    const buttons = Array.from({ length: 12 }, () => ({ pressed: false, value: 0, touched: false }))
    vi.stubGlobal('navigator', {
      getGamepads: () => [{ connected: true, mapping: 'standard', buttons }],
    })
    runtime.start()
    key('keydown', 'KeyZ')
    buttons[4].pressed = true
    controls.pollGamepads()
    key('keyup', 'KeyZ', window)
    runtime.tick(0.1)
    expect(runtime.snapshot().flippers.left).toBeCloseTo(-0.72)
    buttons[9].pressed = true
    controls.pollGamepads()
    expect(runtime.status()).toBe('paused')
    controls.pollGamepads()
    expect(runtime.status()).toBe('paused')
    buttons[9].pressed = false
    controls.pollGamepads()
    buttons[9].pressed = true
    controls.pollGamepads()
    expect(runtime.status()).toBe('running')
  })

  it('removes listeners and pauses when detached', () => {
    const runtime = createPinballRuntime()
    const controls = bindPinballControls(canvas, runtime)
    runtime.start()
    controls.dispose()
    controls.dispose()
    runtime.resume()
    key('keydown', 'Space')
    runtime.tick(1 / 120)
    expect(runtime.snapshot().phase).toBe('ready')
  })
})

it('delegates hardware resume to the session instead of bypassing its guards', () => {
  const root = document.createElement('section')
  root.className = 'od-library-room'
  const target = document.createElement('canvas')
  target.tabIndex = 0
  root.append(target)
  document.body.append(root)
  target.focus()
  const runtime = createPinballRuntime()
  runtime.start()
  runtime.pause()
  const command = vi.fn()
  const buttons = Array.from({ length: 12 }, () => ({ pressed: false, value: 0 }))
  buttons[9].pressed = true
  vi.stubGlobal('navigator', {
    getGamepads: () => [{ connected: true, mapping: 'standard', buttons }],
  })
  const controls = bindPinballControls(target, runtime, () => false, command)
  controls.pollGamepads()
  expect(command).toHaveBeenCalledWith('resume')
  expect(runtime.status()).toBe('paused')
  controls.dispose()
  root.remove()
})
