import content from '../../../../../oneirodex/data/room_games/moonfall-v1.json'
/** Normalized playfield coordinates: x -1..1; y 0..4 (top to drain). */
export const FIXED_STEP = 1 / 120
export const BALL_RADIUS = 0.055
export const TARGETS = [
  { id: 'orbit', name: 'Orbit', x: 0, y: 0.32, radius: 0.16 },
  { id: 'moon', name: 'Moon', x: -0.73, y: 1.1, radius: 0.16 },
  { id: 'aurora', name: 'Aurora', x: 0.73, y: 0.74, radius: 0.16 },
] as const
export type TargetId = (typeof TARGETS)[number]['id']
export function targetPosition(id: TargetId, tick: number) {
  const index = TARGETS.findIndex((target) => target.id === id)
  const target = TARGETS[index]
  const phase = tick / 160 + (index * Math.PI * 2) / 3
  return { x: target.x + Math.sin(phase) * 0.045, y: target.y + (Math.cos(phase) - 1) * 0.035 }
}
export const RAMP_TICKS = 180
/** Two raised crescent orbits, from a rising shot to the opposite return lane. */
export function rampPosition(side: -1 | 1, t: number) {
  const u = 1 - t
  return {
    x: side * (0.55 * u * u * u + 3 * 0.94 * u * u * t - 3 * 0.94 * u * t * t - 0.52 * t * t * t),
    y: 2.48 * u * u * u - 3 * 0.65 * u * u * t - 3 * 0.65 * u * t * t + 3.08 * t * t * t,
    height: 0.045 + Math.sin(Math.PI * t) * 0.23,
  }
}
export const MISSION_NAMES = content.missions.map((mission) => mission.name)
export const MISSION_ROUTES = content.missions.map((mission) => mission.route as TargetId[])
export const MISSION_REQUIREMENTS = content.missions.map((mission) => mission.required)
export const BUMPERS = [
  { x: -0.34, y: 1.3, radius: 0.15 },
  { x: 0.32, y: 1.43, radius: 0.15 },
  { x: 0, y: 1.91, radius: 0.16 },
] as const
export interface Rail {
  ax: number
  ay: number
  bx: number
  by: number
}
export const RAILS: readonly Rail[] = [
  { ax: -0.94, ay: 0.34, bx: -0.58, by: 0.06 },
  { ax: 0.94, ay: 0.34, bx: 0.58, by: 0.06 },
  { ax: -0.93, ay: 2.36, bx: -0.62, by: 2.92 },
  { ax: 0.66, ay: 2.36, bx: 0.5, by: 2.92 },
  { ax: -0.91, ay: 3.11, bx: -0.72, by: 3.5 },
  { ax: 0.66, ay: 3.11, bx: 0.5, by: 3.5 },
]
export const FLIPPERS = {
  left: { x: -0.72, y: 3.5, length: 0.64, rest: 0.24, active: -0.72 },
  right: { x: 0.72, y: 3.5, length: 0.64, rest: Math.PI - 0.24, active: Math.PI + 0.72 },
} as const
