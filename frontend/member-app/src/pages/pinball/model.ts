import {
  BALL_RADIUS,
  BUMPERS,
  FIXED_STEP,
  FLIPPERS,
  MISSION_NAMES,
  MISSION_ROUTES,
  MISSION_REQUIREMENTS,
  RAILS,
  TARGETS,
  targetPosition,
  rampPosition,
  RAMP_TICKS,
} from './table'
import type { Rail } from './table'

export interface MoonfallBall {
  id: number
  x: number
  y: number
  vx: number
  vy: number
  cooldown: number
  captureTicks: number
}
export interface MoonfallInput {
  left: boolean
  right: boolean
  launch: boolean
  recover: boolean
}
export interface MoonfallSettings {
  quality: 'low' | 'standard' | 'high'
  reducedMotion: boolean
  muted: boolean
  volume: number
  highContrast: boolean
}
export interface MoonfallState {
  version: 1
  seed: number
  phase: 'ready' | 'playing' | 'game-over' | 'complete'
  tick: number
  score: number
  best: number
  ballsRemaining: number
  balls: MoonfallBall[]
  nextBallId: number
  missionHits: number[]
  combo: number
  comboTicks: number
  extraBallAwarded: boolean
  recoveries: number
  lastLaunch: boolean
  lastRecover: boolean
  settings: MoonfallSettings
  flippers: { left: number; right: number }
  features: {
    ramps: number
    returns: number
    skillShots: number
    rampTicks: number
    rampSide: -1 | 1
    skillTicks: number
    returnTicks: number
    launchAim: number
  }
}

export function newMoonfall(seed = 0x4d4f4f4e): MoonfallState {
  return {
    version: 1,
    seed: seed >>> 0,
    phase: 'ready',
    tick: 0,
    score: 0,
    best: 0,
    ballsRemaining: 3,
    balls: [],
    nextBallId: 1,
    missionHits: [0, 0, 0],
    combo: 0,
    comboTicks: 0,
    extraBallAwarded: false,
    recoveries: 2,
    lastLaunch: false,
    lastRecover: false,
    settings: {
      quality: 'standard',
      reducedMotion: false,
      muted: true,
      volume: 0.5,
      highContrast: false,
    },
    flippers: { left: FLIPPERS.left.rest, right: FLIPPERS.right.rest },
    features: {
      ramps: 0,
      returns: 0,
      skillShots: 0,
      rampTicks: 0,
      rampSide: 1,
      skillTicks: 0,
      returnTicks: 0,
      launchAim: 0,
    },
  }
}

export const moonfallMission = (state: MoonfallState) =>
  MISSION_NAMES[state.missionHits.findIndex((n, i) => n < MISSION_ROUTES[i].length)] ||
  'Aurora complete'

function award(state: MoonfallState, points: number) {
  state.score = Math.min(2_000_000_000, state.score + points)
  state.best = Math.max(state.best, state.score)
}

function launch(state: MoonfallState, input: MoonfallInput) {
  state.seed = (Math.imul(state.seed, 1664525) + 1013904223) >>> 0
  state.balls = [
    {
      id: state.nextBallId++,
      x: 0.84,
      y: 3.58,
      vx: 0,
      vy: -7.8,
      cooldown: 0,
      captureTicks: 0,
    },
  ]
  state.phase = 'playing'
  state.features.skillTicks = 360
  state.features.rampTicks = 0
  state.features.launchAim =
    input.left && input.right
      ? -0.2
      : input.left
        ? -0.6
        : input.right
          ? -3.3
          : -0.65 - (state.seed % 20) / 100
}

function collideRail(ball: MoonfallBall, rail: Rail, radius = BALL_RADIUS, kick = 0) {
  const dx = rail.bx - rail.ax,
    dy = rail.by - rail.ay
  const t = Math.max(
    0,
    Math.min(1, ((ball.x - rail.ax) * dx + (ball.y - rail.ay) * dy) / (dx * dx + dy * dy)),
  )
  const nx = ball.x - rail.ax - dx * t,
    ny = ball.y - rail.ay - dy * t
  const distance = Math.hypot(nx, ny)
  if (distance >= radius) return
  const ux = distance > 0.00001 ? nx / distance : dy / Math.hypot(dx, dy)
  const uy = distance > 0.00001 ? ny / distance : -dx / Math.hypot(dx, dy)
  ball.x += ux * (radius - distance + 0.0001)
  ball.y += uy * (radius - distance + 0.0001)
  const approach = ball.vx * ux + ball.vy * uy
  if (approach < 0) {
    ball.vx -= 1.75 * approach * ux
    ball.vy -= 1.75 * approach * uy
  }
  if (kick && uy < -0.15) {
    ball.vx += ux * kick * 0.35
    ball.vy = Math.min(ball.vy, -kick)
  }
}

function visitTargets(state: MoonfallState, ball: MoonfallBall) {
  if (ball.cooldown) return
  if (state.features.launchAim && ball.vy < 0 && ball.x > 0.8) return
  const target = TARGETS.find((p) => {
    const position = targetPosition(p.id, state.tick)
    return Math.hypot(ball.x - position.x, ball.y - position.y) < p.radius
  })
  if (!target) return
  if (state.features.skillTicks) {
    state.features.skillTicks = 0
    state.features.skillShots = Math.min(1_000_000, state.features.skillShots + 1)
    award(state, 500)
  }
  ball.cooldown = 30
  const mission = state.missionHits.findIndex((n, i) => n < MISSION_ROUTES[i].length)
  if (mission < 0) return
  if (target.id !== MISSION_ROUTES[mission][state.missionHits[mission]]) {
    award(state, 25)
    return
  }
  state.combo = Math.min(20, state.comboTicks ? state.combo + 1 : 1)
  state.comboTicks = 600
  award(state, 250 * Math.min(state.combo, 4))
  // Light all route steps and meet the table achievements before the closing shot.
  if (
    state.missionHits[mission] === MISSION_ROUTES[mission].length - 1 &&
    Object.entries(MISSION_REQUIREMENTS[mission]).some(
      ([key, needed]) => state.features[key as 'ramps' | 'returns' | 'skillShots'] < needed,
    )
  )
    return
  state.missionHits[mission]++
  if (state.missionHits[mission] < MISSION_ROUTES[mission].length) return
  award(state, (mission + 1) * 1500)
  if (!state.extraBallAwarded) {
    state.ballsRemaining = Math.min(4, state.ballsRemaining + 1)
    state.extraBallAwarded = true
  }
  if (mission === 2) {
    state.phase = 'complete'
    return
  }
  // Orbit capture pauses this ball, then releases it back into play.
  ball.x = 0
  ball.y = 0.42
  ball.vx = 0
  ball.vy = 0
  ball.captureTicks = 90
}

function stepBall(state: MoonfallState, ball: MoonfallBall, input: MoonfallInput) {
  if (ball.cooldown) ball.cooldown--
  const features = state.features
  if (features.launchAim && ball.y < 0.5 && ball.vy < 0) {
    ball.vx = features.launchAim
    ball.vy = -1.8
    features.launchAim = 0
  }
  if (features.rampTicks) {
    features.rampTicks--
    const position = rampPosition(features.rampSide, 1 - features.rampTicks / RAMP_TICKS)
    ball.x = position.x
    ball.y = position.y
    ball.vx = 0
    ball.vy = 0
    if (!features.rampTicks) {
      features.ramps = Math.min(1_000_000, features.ramps + 1)
      ball.vx = features.rampSide * 0.45
      ball.vy = 1.7
      ball.cooldown = 24
      award(state, 750)
    }
    return
  }
  if (
    !ball.captureTicks &&
    !ball.cooldown &&
    ball.vy < -1 &&
    Math.abs(Math.abs(ball.x) - 0.55) < 0.11 &&
    Math.abs(ball.y - 2.48) < 0.11
  ) {
    features.rampSide = ball.x < 0 ? -1 : 1
    features.rampTicks = RAMP_TICKS
    features.skillTicks = 0
    return
  }
  if (
    !ball.captureTicks &&
    !features.returnTicks &&
    ball.vy > 0 &&
    Math.abs(ball.x) > 0.77 &&
    ball.y > 2.74 &&
    ball.y < 3.12
  ) {
    const side = ball.x < 0 ? -1 : 1
    ball.x = side * 0.69
    ball.vx = -side * 0.75
    ball.vy = Math.min(ball.vy, 2)
    features.returnTicks = 120
    features.returns = Math.min(1_000_000, features.returns + 1)
    award(state, 100)
  }
  if (ball.captureTicks) {
    ball.captureTicks--
    if (!ball.captureTicks) {
      ball.vx = 1.8
      ball.vy = 1.7
    }
    return
  }
  visitTargets(state, ball)
  if (ball.captureTicks || state.phase === 'complete') return
  // Adaptive microsteps bound travel to less than half a radius, including fast rails.
  const steps = Math.min(
    24,
    Math.max(1, Math.ceil((Math.hypot(ball.vx, ball.vy) * FIXED_STEP) / (BALL_RADIUS * 0.4))),
  )
  const dt = FIXED_STEP / steps
  for (let i = 0; i < steps; i++) {
    ball.vy += 1.45 * dt
    ball.vx *= 1 - 0.018 * dt
    ball.vy *= 1 - 0.018 * dt
    ball.x += ball.vx * dt
    ball.y += ball.vy * dt
    if (ball.x > 0.94 - BALL_RADIUS) {
      ball.x = 0.94 - BALL_RADIUS
      ball.vx = -Math.abs(ball.vx) * 0.87
    }
    if (ball.x < -0.94 + BALL_RADIUS) {
      ball.x = -0.94 + BALL_RADIUS
      ball.vx = Math.abs(ball.vx) * 0.87
    }
    if (ball.y < BALL_RADIUS) {
      ball.y = BALL_RADIUS
      ball.vy = Math.abs(ball.vy) * 0.87
    }
    for (const rail of RAILS) collideRail(ball, rail)
    for (const side of ['left', 'right'] as const) {
      const flipper = FLIPPERS[side],
        angle = state.flippers[side]
      collideRail(
        ball,
        {
          ax: flipper.x,
          ay: flipper.y,
          bx: flipper.x + Math.cos(angle) * flipper.length,
          by: flipper.y + Math.sin(angle) * flipper.length,
        },
        BALL_RADIUS + 0.036,
        input[side] ? 6.5 : 0,
      )
    }
    for (const bumper of BUMPERS) {
      const dx = ball.x - bumper.x,
        dy = ball.y - bumper.y
      const distance = Math.hypot(dx, dy),
        radius = bumper.radius + BALL_RADIUS
      if (distance >= radius) continue
      const nx = distance > 0.0001 ? dx / distance : 0,
        ny = distance > 0.0001 ? dy / distance : 1
      ball.x = bumper.x + nx * (radius + 0.0001)
      ball.y = bumper.y + ny * (radius + 0.0001)
      const dot = ball.vx * nx + ball.vy * ny
      if (dot < 0) {
        ball.vx -= 1.8 * dot * nx
        ball.vy -= 1.8 * dot * ny
      }
      ball.vx += nx * 0.65
      ball.vy += ny * 0.65
      if (!ball.cooldown) {
        award(state, 50)
        ball.cooldown = 18
      }
    }
    ball.vx = Math.max(-18, Math.min(18, ball.vx))
    ball.vy = Math.max(-18, Math.min(18, ball.vy))
  }
}

export function stepMoonfall(state: MoonfallState, input: MoonfallInput, seconds: number): void {
  if (
    !Number.isFinite(seconds) ||
    seconds <= 0 ||
    state.phase === 'complete' ||
    state.phase === 'game-over'
  )
    return
  const ticks = Math.floor((Math.min(seconds, 0.1) + 1e-10) / FIXED_STEP)
  if (!ticks) return
  if (input.launch && !state.lastLaunch && state.phase === 'ready' && state.ballsRemaining > 0)
    launch(state, input)
  if (input.recover && !state.lastRecover && state.phase === 'playing' && state.recoveries > 0) {
    state.recoveries--
    state.features.rampTicks = 0
    state.features.skillTicks = 0
    state.features.launchAim = 0
    const id = state.balls[0]?.id || state.nextBallId++
    state.balls = [{ id, x: 0, y: 0.7, vx: 0, vy: 0.7, cooldown: 60, captureTicks: 0 }]
  }
  state.lastLaunch = input.launch
  state.lastRecover = input.recover
  for (let t = 0; t < ticks; t++) {
    state.tick++
    if (state.features.skillTicks) state.features.skillTicks--
    if (state.features.returnTicks) state.features.returnTicks--
    if (state.tick >= 10_000_000) {
      state.phase = 'game-over'
      break
    }
    if (state.comboTicks > 0) state.comboTicks--
    else state.combo = 0
    for (const side of ['left', 'right'] as const) {
      const desired = input[side] ? FLIPPERS[side].active : FLIPPERS[side].rest
      state.flippers[side] += Math.max(-0.16, Math.min(0.16, desired - state.flippers[side]))
    }
    if (state.phase !== 'playing') continue
    for (const ball of state.balls) stepBall(state, ball, input)
    if (state.missionHits[2] === MISSION_ROUTES[2].length) break
    const hadBalls = state.balls.length > 0
    state.balls = state.balls.filter((b) => b.y < 4.08)
    if (hadBalls && !state.balls.length) {
      state.ballsRemaining--
      state.phase = state.ballsRemaining > 0 ? 'ready' : 'game-over'
      state.combo = 0
      state.comboTicks = 0
    }
    if (state.tick >= 10_000_000) {
      state.phase = 'game-over'
      break
    }
  }
}

/** Mirror of the bounded server save schema; rejects unknown fields and non-finite data. */
export function validateMoonfall(value: unknown): MoonfallState {
  const fail = () => {
    throw new Error('Unsupported or invalid Moonfall save')
  }
  const object = (v: unknown): Record<string, unknown> => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return fail()
    return v as Record<string, unknown>
  }
  const number = (v: unknown, min: number, max: number, integer = true) => {
    if (
      typeof v !== 'number' ||
      !Number.isFinite(v) ||
      v < min ||
      v > max ||
      (integer && !Number.isInteger(v))
    )
      fail()
  }
  const s = object(value),
    keys = Object.keys(newMoonfall()).sort().join(',')
  if (
    Object.keys(s).sort().join(',') !== keys ||
    s.version !== 1 ||
    !['ready', 'playing', 'game-over', 'complete'].includes(s.phase as string)
  )
    fail()
  for (const [key, max] of Object.entries({
    seed: 0xffffffff,
    tick: 10_000_000,
    score: 2_000_000_000,
    best: 2_000_000_000,
    ballsRemaining: 4,
    nextBallId: 1_000_000,
    combo: 20,
    comboTicks: 600,
    recoveries: 2,
  }))
    number(s[key], key === 'nextBallId' ? 1 : 0, max)
  for (const key of ['extraBallAwarded', 'lastLaunch', 'lastRecover'])
    if (typeof s[key] !== 'boolean') fail()
  if (!Array.isArray(s.missionHits) || s.missionHits.length !== 3) fail()
  ;(s.missionHits as unknown[]).forEach((hit, i) => number(hit, 0, MISSION_ROUTES[i].length))
  const f = object(s.flippers)
  if (Object.keys(f).sort().join(',') !== 'left,right') fail()
  number(f.left, -0.73, 0.25, false)
  number(f.right, Math.PI - 0.25, Math.PI + 0.73, false)
  const settings = object(s.settings)
  if (Object.keys(settings).sort().join(',') !== 'highContrast,muted,quality,reducedMotion,volume')
    fail()
  if (!['low', 'standard', 'high'].includes(settings.quality as string)) fail()
  for (const key of ['highContrast', 'muted', 'reducedMotion'])
    if (typeof settings[key] !== 'boolean') fail()
  number(settings.volume, 0, 1, false)
  const features = object(s.features)
  if (
    Object.keys(features).sort().join(',') !==
    'launchAim,rampSide,rampTicks,ramps,returnTicks,returns,skillShots,skillTicks'
  )
    fail()
  for (const key of ['ramps', 'returns', 'skillShots']) number(features[key], 0, 1_000_000)
  number(features.rampTicks, 0, RAMP_TICKS)
  number(features.skillTicks, 0, 360)
  number(features.returnTicks, 0, 120)
  number(features.launchAim, -3.3, 0, false)
  if (features.rampSide !== -1 && features.rampSide !== 1) fail()
  if (!Array.isArray(s.balls) || s.balls.length > 3) fail()
  const ids = new Set<number>()
  for (const raw of s.balls as unknown[]) {
    const b = object(raw)
    if (Object.keys(b).sort().join(',') !== 'captureTicks,cooldown,id,vx,vy,x,y') fail()
    number(b.id, 1, 1_000_000)
    number(b.x, -1.2, 1.2, false)
    number(b.y, -0.2, 4.2, false)
    number(b.vx, -50, 50, false)
    number(b.vy, -50, 50, false)
    number(b.cooldown, 0, 600)
    number(b.captureTicks, 0, 120)
    if (ids.has(b.id as number)) fail()
    ids.add(b.id as number)
  }
  if ((s.best as number) < (s.score as number)) fail()
  const hits = s.missionHits as number[],
    balls = s.balls as MoonfallBall[]
  for (let i = 1; i < hits.length; i++) {
    if (hits[i] > 0 && hits[i - 1] !== MISSION_ROUTES[i - 1].length) fail()
  }
  if (balls.some((b) => b.id >= (s.nextBallId as number))) fail()
  if (s.phase === 'playing' && (!balls.length || s.ballsRemaining === 0)) fail()
  if (s.phase === 'ready' && (balls.length || s.ballsRemaining === 0)) fail()
  if (s.phase === 'complete' && hits.some((n, i) => n !== MISSION_ROUTES[i].length)) fail()
  hits.forEach((hit, i) => {
    if (
      hit === MISSION_ROUTES[i].length &&
      Object.entries(MISSION_REQUIREMENTS[i]).some(
        ([key, needed]) => (features[key] as number) < needed,
      )
    )
      fail()
  })
  if (s.phase === 'game-over' && s.ballsRemaining !== 0 && (s.tick as number) < 10_000_000) fail()
  return JSON.parse(JSON.stringify(s)) as MoonfallState
}
