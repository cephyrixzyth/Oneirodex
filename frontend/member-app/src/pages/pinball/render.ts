import * as THREE from 'three'
import {
  BALL_RADIUS,
  BUMPERS,
  FLIPPERS,
  MISSION_ROUTES,
  RAILS,
  TARGETS,
  targetPosition,
  rampPosition,
  RAMP_TICKS,
} from './table'
import type { MoonfallState } from './model'
import { disposeRoomGroup, roomBuilder } from '../roomGeometry'
import { createRoomMaterialLibrary } from '../roomMaterials'
import { detailPinballCabinet } from './tableDetail'

const scale = 0.72
export const boardPosition = (x: number, y: number, height = 0.045) =>
  new THREE.Vector3(x * scale, 0.96 + (4 - y) * 0.035 + height, (y - 2) * scale)

/** Actual game state drives these original meshes. No pre-rendered gameplay/video. */
export function createPinballTable(sharedMaterials?: ReturnType<typeof createRoomMaterialLibrary>) {
  const group = new THREE.Group()
  group.name = 'moonfall-pinball-table'
  const materials = sharedMaterials || createRoomMaterialLibrary()
  const b = roomBuilder(group, materials.material)
  detailPinballCabinet(group, materials)
  const brass = '#c9a96b',
    walnut = '#573b2e',
    field = '#152e36'
  b.box('pinball-cabinet', 1.65, 0.34, 3.25, 0, 0.73, 0, walnut, 0, 0.07)
  b.box('pinball-cabinet-apron', 1.72, 0.15, 3.31, 0, 0.9, 0, walnut)
  b.box('pinball-playfield', 1.4, 0.09, 2.96, 0, 0.985, 0, field).rotation.x = Math.atan(
    0.035 / scale,
  )
  for (const x of [-0.67, 0.67])
    for (const z of [-1.24, 1.24]) {
      b.strut(
        'pinball-leg',
        new THREE.Vector3(x, 0.68, z),
        new THREE.Vector3(x * 1.08, 0.04, z * 1.04),
        0.045,
        brass,
      )
      b.mesh(
        'pinball-foot',
        new THREE.CylinderGeometry(0.07, 0.08, 0.05, 12),
        b.material('#222a28'),
        x * 1.08,
        0.025,
        z * 1.04,
      )
    }
  for (const side of [-1, 1]) {
    const rail = b.box('pinball-glass-rail', 0.08, 0.09, 3.15, side * 0.73, 1.09, 0, brass, 0.75)
    rail.rotation.x = Math.atan(0.035 / scale)
    b.box('pinball-side-inlay', 0.012, 0.035, 2.88, side * 0.831, 0.77, 0, '#85b5a9', 0.4)
  }
  RAILS.forEach((rail, i) =>
    b.strut(
      'pinball-rail-' + i,
      boardPosition(rail.ax, rail.ay, 0.025),
      boardPosition(rail.bx, rail.by, 0.025),
      0.022,
      brass,
    ),
  )
  for (const x of [-0.94, 0.94])
    b.strut(
      'pinball-boundary-rail',
      boardPosition(x, 0.1, 0.025),
      boardPosition(x, 3.4, 0.025),
      0.022,
      brass,
    )
  b.strut('pinball-top-rail', boardPosition(-0.9, 0.03), boardPosition(0.9, 0.03), 0.022, brass)
  for (const side of [-1, 1] as const) {
    const ramp = new THREE.Group()
    ramp.name = side < 0 ? 'pinball-ramp-left' : 'pinball-ramp-right'
    group.add(ramp)
    for (const edge of [-1, 1]) {
      const points = Array.from({ length: 33 }, (_, i) => {
        const p = rampPosition(side, i / 32)
        return boardPosition(p.x + edge * 0.07, p.y, p.height - 0.018)
      })
      const rail = new THREE.Mesh(
        new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), 64, 0.009, 6, false),
        b.material(brass, 0.7),
      )
      ramp.add(rail)
    }
    const center = Array.from({ length: 33 }, (_, i) => {
      const p = rampPosition(side, i / 32)
      return boardPosition(p.x, p.y, p.height - 0.032)
    })
    const lane = new THREE.Mesh(
      new THREE.TubeGeometry(new THREE.CatmullRomCurve3(center), 64, 0.04, 8, false),
      new THREE.MeshPhysicalMaterial({
        color: new THREE.Color('#82b7a4'),
        transparent: true,
        opacity: 0.25,
        roughness: 0.25,
        depthWrite: false,
      }),
    )
    ramp.add(lane)
    b.strut(
      'pinball-return-lane-' + side,
      boardPosition(side * 0.87, 2.74, 0.02),
      boardPosition(side * 0.66, 3.16, 0.02),
      0.012,
      brass,
    )
  }
  const targets = new Map<string, THREE.MeshStandardMaterial>()
  const targetNodes = new Map<string, THREE.Object3D[]>()
  for (const target of TARGETS) {
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color('#b3dcc1'),
      metalness: 0.35,
      roughness: 0.35,
      emissive: '#77dfae',
      emissiveIntensity: 0.2,
    })
    const ring = b.mesh(
      'pinball-target-' + target.id,
      new THREE.TorusGeometry(target.radius * scale, 0.016, 8, 32),
      material,
    )
    ring.position.copy(boardPosition(target.x, target.y, 0.012))
    ring.rotation.x = Math.PI / 2
    targets.set(target.id, material)
    const base = b.mesh(
      'pinball-target-medallion-' + target.id,
      new THREE.CylinderGeometry(0.065, 0.065, 0.012, 20),
      b.material('#ac935a', 0.6),
    )
    base.position.copy(boardPosition(target.x, target.y, 0.015))
    let symbolGeometry: THREE.BufferGeometry
    if (target.id === 'orbit') symbolGeometry = new THREE.TorusGeometry(0.045, 0.008, 6, 20)
    else {
      const shape = new THREE.Shape()
      if (target.id === 'moon') {
        shape.absarc(0, 0, 0.048, Math.PI * 0.3, Math.PI * 1.7, false)
        shape.quadraticCurveTo(
          -0.018,
          0,
          0.048 * Math.cos(Math.PI * 0.3),
          0.048 * Math.sin(Math.PI * 0.3),
        )
      } else {
        for (let i = 0; i < 10; i++) {
          const a = (i * Math.PI) / 5,
            r = i % 2 ? 0.023 : 0.052
          if (!i) shape.moveTo(Math.sin(a) * r, Math.cos(a) * r)
          else shape.lineTo(Math.sin(a) * r, Math.cos(a) * r)
        }
        shape.closePath()
      }
      symbolGeometry = new THREE.ShapeGeometry(shape)
    }
    const symbol = b.mesh(
      'pinball-symbol-' + target.id,
      symbolGeometry,
      b.material('#f2e7b0', 0.1, 0.6, 0.25),
    )
    symbol.position.copy(boardPosition(target.x, target.y, 0.035))
    symbol.rotation.x = -Math.PI / 2
    targetNodes.set(target.id, [ring, base, symbol])
  }
  BUMPERS.forEach((bumper, i) => {
    const center = boardPosition(bumper.x, bumper.y, 0.04)
    b.mesh(
      'pinball-bumper-' + i,
      new THREE.CylinderGeometry(bumper.radius * scale, bumper.radius * scale, 0.09, 28),
      b.material('#a98a50', 0.7),
      center.x,
      center.y,
      center.z,
    )
    const cap = b.mesh(
      'pinball-bumper-cap',
      new THREE.SphereGeometry(bumper.radius * scale * 0.9, 20, 12),
      b.material('#6ba993', 0.3, 0.25, 0.3),
      center.x,
      center.y + 0.035,
      center.z,
    )
    cap.scale.y = 0.4
  })
  const flippers = {} as Record<'left' | 'right', THREE.Group>
  for (const side of ['left', 'right'] as const) {
    const data = FLIPPERS[side],
      pivot = new THREE.Group()
    pivot.name = 'pinball-flipper-' + side
    pivot.position.copy(boardPosition(data.x, data.y, 0.032))
    group.add(pivot)
    const fb = roomBuilder(pivot)
    fb.box(
      'flipper-rubber',
      data.length * scale,
      0.062,
      0.095,
      (data.length * scale) / 2,
      0,
      0,
      '#e8d6ad',
      0,
      0.03,
    )
    fb.box(
      'flipper-brass-inlay',
      data.length * scale * 0.8,
      0.009,
      0.04,
      (data.length * scale) / 2,
      0.038,
      0,
      brass,
      0.7,
    )
    fb.mesh(
      'flipper-hinge',
      new THREE.CylinderGeometry(0.043, 0.043, 0.08, 16),
      fb.material(brass, 0.7),
    )
    pivot.rotation.y = -data.rest
    flippers[side] = pivot
  }
  const balls = Array.from({ length: 3 }, (_, i) => {
    const mesh = b.mesh(
      'pinball-ball-slot-' + i,
      new THREE.SphereGeometry(BALL_RADIUS * scale, 18, 14),
      b.material('#dce7e2', 0.82, 0.14),
    )
    mesh.visible = false
    return mesh
  })
  b.box('pinball-backboard', 1.7, 1.09, 0.17, 0, 1.64, -1.68, walnut, 0, 0.08)
  b.box('pinball-score-inset', 1.48, 0.43, 0.035, 0, 1.72, -1.58, '#0b1c1e')
  const moon = b.mesh(
    'pinball-crescent',
    new THREE.TorusGeometry(0.16, 0.026, 8, 32, Math.PI * 1.52),
    b.material(brass, 0.6),
    0,
    2.045,
    -1.55,
  )
  moon.rotation.z = -0.8
  for (let i = 0; i < 9; i++) {
    const angle = i * 2.4
    b.mesh(
      'pinball-backboard-star',
      new THREE.SphereGeometry(0.009 + (i % 3) * 0.003, 6, 4),
      b.material('#d4d5ad', 0.1, 0.4, 0.5),
      Math.sin(angle) * 0.56,
      2.0 + Math.cos(angle) * 0.11,
      -1.55,
    )
  }
  const segmentMaterial = b.material('#a9e9bd', 0.1, 0.45, 0.7)
  const digits = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), segmentMaterial, 70)
  digits.name = 'pinball-live-score'
  digits.castShadow = false
  group.add(digits)
  const patterns = [
    '1111110',
    '0110000',
    '1101101',
    '1111001',
    '0110011',
    '1011011',
    '1011111',
    '1110000',
    '1111111',
    '1111011',
  ]
  const segmentLayout = [
    [0, 0.1, 0.075, 0.014],
    [0.042, 0.051, 0.014, 0.075],
    [0.042, -0.051, 0.014, 0.075],
    [0, -0.1, 0.075, 0.014],
    [-0.042, -0.051, 0.014, 0.075],
    [-0.042, 0.051, 0.014, 0.075],
    [0, 0, 0.075, 0.014],
  ]
  const object = new THREE.Object3D()
  let lastScore = -1,
    disposed = false
  const actionMeshes: THREE.Mesh[] = []
  for (const [side, action] of [
    [-1, 'left'],
    [1, 'right'],
  ] as const) {
    const button = b.mesh(
      'pinball-control-' + action,
      new THREE.CylinderGeometry(0.085, 0.085, 0.04, 20),
      b.material('#83caae', 0.25, 0.3, 0.25),
      side * 0.85,
      0.86,
      1.18,
      0,
      0,
      Math.PI / 2,
    )
    button.userData.action = '@pinball-' + action
    actionMeshes.push(button)
  }
  const launch = b.mesh(
    'pinball-control-launch',
    new THREE.CylinderGeometry(0.06, 0.06, 0.1, 16),
    b.material(brass, 0.75),
    0.58,
    0.82,
    1.7,
    Math.PI / 2,
  )
  launch.userData.action = '@pinball-launch'
  actionMeshes.push(launch)
  return {
    group,
    actionMeshes,
    update(state: MoonfallState) {
      if (disposed) return
      balls.forEach((mesh, i) => {
        const ball = state.balls[i]
        mesh.visible = Boolean(ball)
        if (ball)
          mesh.position.copy(
            boardPosition(
              ball.x,
              ball.y,
              state.features.rampTicks
                ? rampPosition(state.features.rampSide, 1 - state.features.rampTicks / RAMP_TICKS)
                    .height
                : ball.captureTicks
                  ? 0.12
                  : 0.045,
            ),
          )
      })
      for (const side of ['left', 'right'] as const)
        flippers[side].rotation.y = -state.flippers[side]
      const mission = state.missionHits.findIndex((hit, i) => hit < MISSION_ROUTES[i].length)
      const next = mission < 0 ? '' : MISSION_ROUTES[mission][state.missionHits[mission]]
      for (const [id, material] of targets) {
        const position = targetPosition(id as (typeof TARGETS)[number]['id'], state.tick)
        targetNodes
          .get(id)!
          .forEach((node, index) =>
            node.position.copy(boardPosition(position.x, position.y, [0.012, 0.015, 0.035][index])),
          )
        material.color.set(
          state.settings.highContrast ? (id === next ? '#ffffcf' : '#172b26') : '#83caae',
        )
        material.emissive.set(state.settings.highContrast ? '#fff2a6' : '#77dfae')
        material.emissiveIntensity = state.phase === 'complete' ? 1.5 : id === next ? 1.1 : 0.07
      }
      if (state.score === lastScore) return
      lastScore = state.score
      const score = String(state.score).padStart(10, ' ')
      for (let digit = 0; digit < 10; digit++)
        for (let segment = 0; segment < 7; segment++) {
          const [x, y, width, height] = segmentLayout[segment]
          const on = patterns[Number(score[digit])]?.[segment] === '1' && score[digit] !== ' '
          object.position.set((digit - 4.5) * 0.125 + x, 1.72 + y, on ? -1.548 : -1.64)
          object.scale.set(width, height, 0.012)
          object.updateMatrix()
          digits.setMatrixAt(digit * 7 + segment, object.matrix)
        }
      digits.instanceMatrix.needsUpdate = true
      digits.computeBoundingSphere()
    },
    dispose() {
      if (!disposed) {
        disposed = true
        disposeRoomGroup(group, materials.owned)
        if (!sharedMaterials) materials.dispose()
      }
    },
  }
}
