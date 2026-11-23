import { expect, test } from 'vitest'
import { newMoonfall, stepMoonfall, validateMoonfall } from './model'
import { targetPosition, rampPosition, RAMP_TICKS } from './table'
const idle = { left: false, right: false, launch: false, recover: false }
test('orbital sensors move on a bounded deterministic path', () => {
  expect(targetPosition('orbit', 0)).not.toEqual(targetPosition('orbit', 120))
  expect(targetPosition('moon', 120)).toEqual(targetPosition('moon', 120))
})
test('a rising ramp shot follows its elevated route and returns to the opposite flipper', () => {
  const state = newMoonfall()
  stepMoonfall(state, { ...idle, launch: true }, 1 / 120)
  state.features.skillTicks = 0
  Object.assign(state.balls[0], { x: -0.55, y: 2.48, vx: 0, vy: -3, cooldown: 0 })
  stepMoonfall(state, idle, 1 / 120)
  expect(state.features.rampTicks).toBe(RAMP_TICKS)
  for (let i = 0; i < RAMP_TICKS; i++) stepMoonfall(state, idle, 1 / 120)
  expect(state.features.ramps).toBe(1)
  expect(state.balls[0].x).toBeCloseTo(rampPosition(-1, 1).x)
  expect(state.balls[0].vy).toBeGreaterThan(0)
  expect(state.score).toBeGreaterThanOrEqual(750)
  expect(validateMoonfall(state)).toEqual(state)
})
test('aimed launch can earn a skill shot through ordinary fixed-step play', () => {
  const state = newMoonfall(42)
  stepMoonfall(state, { ...idle, left: true, launch: true }, 1 / 120)
  for (let i = 0; i < 360 && !state.features.skillShots; i++)
    stepMoonfall(state, { ...idle, left: true }, 1 / 120)
  expect(state.features.skillShots).toBe(1)
  expect(state.score).toBeGreaterThanOrEqual(500)
})
test('a return lane catches a falling side shot and feeds a reachable flipper', () => {
  const state = newMoonfall()
  stepMoonfall(state, { ...idle, launch: true }, 1 / 120)
  Object.assign(state.balls[0], { x: -0.84, y: 2.88, vx: -0.2, vy: 2, cooldown: 0 })
  stepMoonfall(state, idle, 1 / 120)
  expect(state.features.returns).toBe(1)
  expect(state.balls[0].vx).toBeGreaterThan(0)
})

test('reaches a finale using only continuous legal controller inputs, with no state injection', () => {
  const state = newMoonfall(4)
  for (let tick = 0; tick < 120 * 1800; tick++) {
    const flip = tick % 60 < 27
    stepMoonfall(
      state,
      {
        left: flip,
        right: flip,
        launch: state.phase === 'ready' && !state.lastLaunch,
        recover: false,
      },
      1 / 120,
    )
    if (state.phase === 'complete' || state.phase === 'game-over') break
  }
  expect(state.phase).toBe('complete')
  expect(state.features.ramps).toBeGreaterThan(0)
  expect(validateMoonfall(state)).toEqual(state)
})

test('a short held-flipper loop cannot substitute for the authored mission session', () => {
  const state = newMoonfall(42)
  for (let tick = 0; tick < 120 * 120; tick++) {
    stepMoonfall(
      state,
      {
        left: true,
        right: true,
        launch: state.phase === 'ready' && !state.lastLaunch,
        recover: false,
      },
      1 / 120,
    )
    if (state.phase === 'complete' || state.phase === 'game-over') break
  }
  expect(state.phase).not.toBe('complete')
})

test.each([
  { left: true, right: false, id: 'orbit' as const },
  { left: false, right: true, id: 'aurora' as const },
  { left: true, right: true, id: 'moon' as const },
])('launch steering reaches $id as its first skill-shot target', ({ left, right, id }) => {
  const state = newMoonfall(42)
  for (let tick = 0; tick < 360; tick++) {
    stepMoonfall(state, { left, right, launch: tick === 0, recover: false }, 1 / 120)
    if (state.features.skillShots) break
  }
  expect(state.features.skillShots).toBe(1)
  const target = targetPosition(id, state.tick),
    ball = state.balls[0]
  expect(Math.hypot(ball.x - target.x, ball.y - target.y)).toBeLessThan(0.21)
})
