import { describe, expect, it } from 'vitest'
import { newMoonfall, stepMoonfall, validateMoonfall } from './model'
import { MISSION_ROUTES, TARGETS } from './table'
import savedRun from '../../../../../tests/fixtures/moonfall-save-v1.json'

const idle = { left: false, right: false, launch: false, recover: false }
const ball = (x: number, y: number, vx = 0, vy = 0) => ({
  id: 1,
  x,
  y,
  vx,
  vy,
  cooldown: 0,
  captureTicks: 0,
})
function playing() {
  const state = newMoonfall(42)
  stepMoonfall(state, { ...idle, launch: true }, 1 / 120)
  return state
}

describe('Moonfall game and physics', () => {
  it('includes versioned game settings and rejects unsafe setting values', () => {
    const state = newMoonfall()
    expect(state.settings).toEqual({
      quality: 'standard',
      reducedMotion: false,
      muted: true,
      volume: 0.5,
      highContrast: false,
    })
    for (const settings of [
      { ...state.settings, volume: Infinity },
      { ...state.settings, volume: 1.1 },
      { ...state.settings, quality: 'ultra' },
    ]) {
      expect(() => validateMoonfall({ ...state, settings })).toThrow()
    }
  })
  it('accepts the exact shared server/client fixture', () => {
    expect(validateMoonfall(savedRun)).toEqual(savedRun)
  })
  it('starts with three balls and launches once per press, without consuming a spare on launch', () => {
    const state = newMoonfall(42)
    expect(state.phase).toBe('ready')
    expect(state.ballsRemaining).toBe(3)
    stepMoonfall(state, { ...idle, launch: true }, 1 / 120)
    expect(state.phase).toBe('playing')
    expect(state.balls).toHaveLength(1)
    expect(state.balls[0].vy).toBeLessThan(0)
    for (let i = 0; i < 10; i++) stepMoonfall(state, { ...idle, launch: true }, 1 / 120)
    expect(state.balls).toHaveLength(1)
    expect(state.ballsRemaining).toBe(3)
  })

  it('bounces a fast ball at the rail instead of tunneling through it', () => {
    const state = playing()
    state.balls = [ball(0.87, 2.2, 16, 0)]
    stepMoonfall(state, idle, 0.1)
    expect(state.balls).toHaveLength(1)
    expect(state.balls[0].x).toBeLessThan(0.96)
    expect(state.balls[0].vx).toBeLessThan(0)
    expect(state.score).toBe(0)
  })

  it('leaves the center bottom open and ends a run after three deliberate drains', () => {
    const state = playing()
    for (let spare = 2; spare >= 0; spare--) {
      state.balls = [ball(0, 3.96, 0, 4)]
      stepMoonfall(state, idle, 0.1)
      expect(state.balls).toHaveLength(0)
      expect(state.ballsRemaining).toBe(spare)
      expect(state.phase).toBe(spare ? 'ready' : 'game-over')
      if (spare) stepMoonfall(state, { ...idle, launch: true }, 1 / 120)
      stepMoonfall(state, idle, 1 / 120)
    }
  })

  it('does not consume a spare while another multiball remains in play', () => {
    const state = playing()
    state.balls = [ball(0, 3.99, 0, 3), { ...ball(0, 2), id: 2 }]
    stepMoonfall(state, idle, 1 / 30)
    expect(state.balls).toHaveLength(1)
    expect(state.ballsRemaining).toBe(3)
  })

  it.each(['left', 'right'] as const)('lets the %s flipper return a falling ball', (side) => {
    const state = playing()
    state.balls = [ball(side === 'left' ? -0.4 : 0.4, 3.12, 0, 2)]
    for (let i = 0; i < 8; i++) stepMoonfall(state, { ...idle, [side]: true }, 1 / 120)
    expect(state.balls[0].vy).toBeLessThan(0)
  })

  it('completes three ordered missions and finishes with a visible result', () => {
    const state = playing()
    Object.assign(state.features, { ramps: 6, returns: 8, skillShots: 2 })
    for (let mission = 0; mission < 3; mission++) {
      for (const targetId of MISSION_ROUTES[mission]) {
        const target = TARGETS.find((t) => t.id === targetId)!
        state.balls = [ball(target.x, target.y)]
        stepMoonfall(state, idle, 1 / 120)
      }
      expect(state.missionHits[mission]).toBe(MISSION_ROUTES[mission].length)
    }
    expect(state.phase).toBe('complete')
    expect(state.score).toBeGreaterThan(0)
    expect(state.best).toBe(state.score)
    const result = structuredClone(state)
    stepMoonfall(state, { ...idle, launch: true }, 0.1)
    expect(state).toEqual(result)
  })

  it('does not award a mission hit when the wrong target is struck', () => {
    const state = playing()
    const target = TARGETS.find((t) => t.id !== MISSION_ROUTES[0][0])!
    state.balls = [ball(target.x, target.y)]
    stepMoonfall(state, idle, 1 / 120)
    expect(state.missionHits).toEqual([0, 0, 0])
  })

  it('awards the extra ball only once and releases the orbit capture', () => {
    const state = playing()
    Object.assign(state.features, { ramps: 6, returns: 8, skillShots: 2 })
    for (let mission = 0; mission < 2; mission++) {
      for (const id of MISSION_ROUTES[mission]) {
        const target = TARGETS.find((t) => t.id === id)!
        state.balls = [ball(target.x, target.y)]
        stepMoonfall(state, idle, 1 / 120)
      }
      expect(state.ballsRemaining).toBe(4)
      expect(state.balls[0].captureTicks).toBeGreaterThan(0)
      for (let tick = 0; tick < 91; tick++) stepMoonfall(state, idle, 1 / 120)
      expect(state.balls[0].captureTicks).toBe(0)
      expect(state.balls[0].vy).toBeGreaterThan(0)
    }
  })

  it('does not farm score on repeated bumper contacts within a cooldown', () => {
    const state = playing()
    state.balls = [ball(0, 1.91, 0, -0.1)]
    stepMoonfall(state, idle, 1 / 120)
    const score = state.score
    expect(score).toBe(50)
    for (let i = 0; i < 10; i++) {
      Object.assign(state.balls[0], { x: 0, y: 1.91, vx: 0, vy: -0.1 })
      stepMoonfall(state, idle, 1 / 120)
    }
    expect(state.score).toBe(score)
  })

  it('naturally reaches a result after a seeded unassisted run, without a debug drain', () => {
    const state = newMoonfall(218)
    for (let i = 0; i < 36_000 && state.phase !== 'game-over'; i++) {
      stepMoonfall(
        state,
        { ...idle, launch: state.phase === 'ready' && !state.lastLaunch },
        1 / 120,
      )
    }
    expect(state.phase).toBe('game-over')
    expect(state.ballsRemaining).toBe(0)
  })

  it('bounds catch-up and ignores invalid elapsed time', () => {
    const state = playing()
    const before = structuredClone(state)
    for (const delta of [0, -1, NaN, Infinity]) stepMoonfall(state, idle, delta)
    expect(state).toEqual(before)
    stepMoonfall(state, idle, 3600)
    expect(state.tick - before.tick).toBeLessThanOrEqual(12)
    expect(state.balls.every((b) => Number.isFinite(b.x) && Number.isFinite(b.y))).toBe(true)
  })

  it('ends at the bounded session clock even while waiting to launch', () => {
    const state = newMoonfall(42)
    state.tick = 9_999_999
    stepMoonfall(state, idle, 1 / 120)
    expect(state.phase).toBe('game-over')
    expect(state.tick).toBe(10_000_000)
    expect(validateMoonfall(state)).toEqual(state)
  })

  it('offers only two explicit recoveries and never creates score or extra balls', () => {
    const state = playing()
    for (let i = 0; i < 3; i++) {
      stepMoonfall(state, { ...idle, recover: true }, 1 / 120)
      stepMoonfall(state, idle, 1 / 120)
    }
    expect(state.recoveries).toBe(0)
    expect(state.ballsRemaining).toBe(3)
    expect(state.score).toBe(0)
    expect(state.balls).toHaveLength(1)
  })

  it('round-trips a run and continues deterministically without sharing mutable arrays', () => {
    const state = playing()
    for (let i = 0; i < 120; i++) stepMoonfall(state, { ...idle, left: i % 7 < 3 }, 1 / 120)
    const restored = validateMoonfall(JSON.parse(JSON.stringify(state)))
    expect(restored).toEqual(state)
    expect(restored.balls).not.toBe(state.balls)
    for (let i = 0; i < 240; i++) {
      const input = { ...idle, left: i % 11 < 4, right: i % 13 < 5 }
      stepMoonfall(state, input, 1 / 120)
      stepMoonfall(restored, input, 1 / 120)
    }
    expect(restored).toEqual(state)
  })

  it.each([
    (s: Record<string, unknown>) => {
      s.version = 2
    },
    (s: Record<string, unknown>) => {
      s.score = Infinity
    },
    (s: Record<string, unknown>) => {
      s.score = true
    },
    (s: Record<string, unknown>) => {
      s.ballsRemaining = -1
    },
    (s: Record<string, unknown>) => {
      s.missionHits = [0, 0, 99]
    },
    (s: Record<string, unknown>) => {
      s.unexpected = 'private'
    },
    (s: Record<string, unknown>) => {
      s.balls = [ball(NaN, 2)]
    },
    (s: Record<string, unknown>) => {
      s.balls = [ball(0, 2), ball(0, 2), ball(0, 2), ball(0, 2)]
    },
    (s: Record<string, unknown>) => {
      s.phase = 'playing'
      s.balls = []
    },
    (s: Record<string, unknown>) => {
      s.phase = 'complete'
    },
    (s: Record<string, unknown>) => {
      s.missionHits = [0, 1, 0]
    },
  ])('rejects invalid or unsupported saves without returning their values', (change) => {
    const input = JSON.parse(JSON.stringify(playing()))
    change(input)
    expect(() => validateMoonfall(input)).toThrow('Unsupported or invalid Moonfall save')
  })
})
