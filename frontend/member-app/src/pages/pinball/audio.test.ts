import { expect, test, vi } from 'vitest'
import { createMoonfallAudio } from './audio'
import { newMoonfall } from './model'
test('requires an explicit unmuted gesture and closes its audio context', () => {
  const frequency = { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }
  const gain = { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }
  const oscillator = {
    frequency,
    connect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    disconnect: vi.fn(),
    onended: null,
  }
  const context = {
    currentTime: 1,
    state: 'running',
    destination: {},
    createOscillator: vi.fn(() => oscillator),
    createGain: vi.fn(() => ({ gain, connect: vi.fn(), disconnect: vi.fn() })),
    close: vi.fn(async () => {}),
    resume: vi.fn(async () => {}),
  }
  const factory = vi.fn(() => context as unknown as AudioContext)
  const audio = createMoonfallAudio(factory)
  const state = newMoonfall()
  audio.observe(state, 'running')
  expect(factory).not.toHaveBeenCalled()
  audio.unlock(state.settings)
  expect(factory).not.toHaveBeenCalled()
  state.settings.muted = false
  audio.unlock(state.settings)
  state.score = 100
  audio.observe(state, 'running')
  expect(oscillator.start).toHaveBeenCalledOnce()
  audio.dispose()
  audio.dispose()
  expect(context.close).toHaveBeenCalledOnce()
})
