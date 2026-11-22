import { describe, expect, it, vi } from 'vitest'
import { createPinballRuntime } from './runtime'
import savedRun from '../../../../../tests/fixtures/moonfall-save-v1.json'

describe('Moonfall simulation lifecycle', () => {
  it('does not simulate before an explicit start and only emits bounded snapshots', () => {
    const changed = vi.fn()
    const runtime = createPinballRuntime(changed)
    runtime.tick(1)
    expect(runtime.snapshot().tick).toBe(0)
    expect(runtime.status()).toBe('idle')
    runtime.start()
    runtime.input('launch', true)
    runtime.tick(0.1)
    expect(runtime.status()).toBe('running')
    expect(runtime.snapshot().balls).toHaveLength(1)
    expect(changed.mock.calls[0][0].reason).toBe('start')
    expect(changed.mock.calls.length).toBeLessThan(4)
  })

  it('accumulates fractional frames and clamps a background-length time jump', () => {
    const runtime = createPinballRuntime()
    runtime.start()
    runtime.tick(1 / 240)
    expect(runtime.snapshot().tick).toBe(0)
    runtime.tick(1 / 240)
    expect(runtime.snapshot().tick).toBe(1)
    runtime.tick(600)
    expect(runtime.snapshot().tick).toBeLessThanOrEqual(13)
  })

  it('preserves a short launch press even when released before the next frame', () => {
    const runtime = createPinballRuntime()
    runtime.start()
    runtime.input('launch', true)
    runtime.input('launch', false)
    runtime.tick(1 / 120)
    expect(runtime.snapshot().phase).toBe('playing')
    expect(runtime.snapshot().balls).toHaveLength(1)
  })

  it('pauses without time advancement, releases held controls and resumes explicitly', () => {
    const runtime = createPinballRuntime()
    runtime.start()
    runtime.input('left', true)
    runtime.tick(0.05)
    runtime.pause()
    const paused = runtime.snapshot()
    runtime.tick(60)
    runtime.input('right', true)
    expect(runtime.snapshot()).toEqual(paused)
    runtime.resume()
    runtime.tick(0.05)
    expect(runtime.snapshot().flippers.left).toBeGreaterThan(paused.flippers.left)
    expect(runtime.snapshot().flippers.right).toBeCloseTo(savedRun.flippers.right)
  })

  it('restores a validated saved run paused and leaves input inactive', () => {
    const runtime = createPinballRuntime()
    runtime.restore(savedRun)
    expect(runtime.status()).toBe('paused')
    runtime.tick(20)
    expect(runtime.snapshot()).toEqual(savedRun)
    runtime.resume()
    runtime.tick(1 / 120)
    expect(runtime.snapshot().tick).toBe(savedRun.tick + 1)
  })

  it('invalid restore does not replace the currently valid run', () => {
    const runtime = createPinballRuntime()
    runtime.restore(savedRun)
    const before = runtime.snapshot()
    expect(() => runtime.restore({ ...savedRun, version: 999 })).toThrow()
    expect(runtime.snapshot()).toEqual(before)
  })

  it('keeps a flipper held until all input sources release it', () => {
    const runtime = createPinballRuntime()
    runtime.start()
    runtime.input('left', true, 'keyboard')
    runtime.input('left', true, 'gamepad')
    runtime.input('left', false, 'keyboard')
    runtime.tick(0.1)
    expect(runtime.snapshot().flippers.left).toBeCloseTo(-0.72)
    runtime.releaseSource('gamepad')
    runtime.tick(0.1)
    expect(runtime.snapshot().flippers.left).toBeCloseTo(0.24)
  })

  it('reports a real terminal drain once and stops simulating the result', () => {
    const changed = vi.fn()
    const runtime = createPinballRuntime(changed)
    const state = structuredClone(savedRun)
    state.ballsRemaining = 1
    state.balls[0].x = 0
    state.balls[0].y = 4
    state.balls[0].vy = 4
    runtime.restore(state)
    runtime.resume()
    runtime.tick(0.1)
    expect(runtime.status()).toBe('result')
    expect(runtime.snapshot().phase).toBe('game-over')
    const ended = runtime.snapshot()
    runtime.tick(5)
    expect(runtime.snapshot()).toEqual(ended)
    expect(changed.mock.calls.filter(([event]) => event.reason === 'result')).toHaveLength(1)
  })

  it('starts a new run with the personal best but fresh balls and missions', () => {
    const runtime = createPinballRuntime()
    runtime.restore(savedRun)
    runtime.start()
    expect(runtime.snapshot().best).toBe(savedRun.best)
    expect(runtime.snapshot().score).toBe(0)
    expect(runtime.snapshot().missionHits).toEqual([0, 0, 0])
    expect(runtime.snapshot().ballsRemaining).toBe(3)
  })

  it('preserves chosen settings across a new run and emits an explicit settings event', () => {
    const changed = vi.fn()
    const runtime = createPinballRuntime(changed)
    runtime.setSettings({ muted: false, volume: 0.25, quality: 'low' })
    runtime.start()
    expect(runtime.snapshot().settings).toMatchObject({
      muted: false,
      volume: 0.25,
      quality: 'low',
    })
    expect(changed.mock.calls.some(([event]) => event.reason === 'settings')).toBe(true)
  })

  it('disposes idempotently and cannot emit or resume private state afterward', () => {
    const changed = vi.fn()
    const runtime = createPinballRuntime(changed)
    runtime.restore(savedRun)
    runtime.dispose()
    const calls = changed.mock.calls.length
    runtime.dispose()
    runtime.start()
    runtime.resume()
    runtime.tick(1)
    expect(runtime.status()).toBe('disposed')
    expect(changed).toHaveBeenCalledTimes(calls)
    expect(runtime.snapshot().score).toBe(0)
  })
})
