import * as THREE from 'three'
import { roomBuilder } from './roomGeometry'
import type { createRoomMaterialLibrary } from './roomMaterials'

export function detailTelescope(
  head: THREE.Group,
  palette: ReturnType<typeof createRoomMaterialLibrary>,
) {
  const b = roomBuilder(head, palette.material),
    axis = new THREE.Vector3(0, Math.cos(0.8), Math.sin(0.8))
  b.box('telescope-saddle-mount', 0.12, 0.28, 0.12, 0, 0.1, 0, '#202c29', 0.5, 0.015)
  for (const offset of [-0.45, -0.32, 0.37, 0.48]) {
    const ring = b.mesh(
      'telescope-retaining-ring',
      new THREE.TorusGeometry(0.14 - 0.038 * offset, 0.011, 8, 32),
      b.material('#c9a96b', 0.8, 0.28),
      0,
      0.27 + axis.y * offset,
      axis.z * offset,
    )
    ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), axis)
  }
  b.mesh(
    'telescope-focus-barrel',
    new THREE.CylinderGeometry(0.052, 0.06, 0.25, 24),
    b.material('#152421', 0.3, 0.38),
    0,
    0.27 - axis.y * 0.63,
    -axis.z * 0.63,
    0.8,
  )
  b.mesh(
    'telescope-focus-eyecup',
    new THREE.CylinderGeometry(0.073, 0.065, 0.06, 24),
    b.material('#111a18', 0.1, 0.82),
    0,
    0.27 - axis.y * 0.78,
    -axis.z * 0.78,
    0.8,
  )
  b.mesh(
    'telescope-focus-wheel',
    new THREE.CylinderGeometry(0.047, 0.047, 0.08, 24),
    b.material('#c9a96b', 0.8, 0.3),
    0.17,
    0.03,
    -0.22,
    0,
    0,
    Math.PI / 2,
  )
  for (const side of [-1, 1])
    b.mesh(
      'telescope-pivot-bearing',
      new THREE.CylinderGeometry(0.06, 0.06, 0.07, 24),
      b.material('#c9a96b', 0.75, 0.3),
      side * 0.18,
      0,
      0,
      0,
      0,
      Math.PI / 2,
    )
}

export function detailOrrery(
  orrery: THREE.Group,
  palette: ReturnType<typeof createRoomMaterialLibrary>,
) {
  const b = roomBuilder(orrery, palette.material)
  for (const [radius, x, z] of [
    [0.19, 0, 0],
    [0.095, 0.26, 0.12],
  ] as const) {
    const shape = new THREE.Shape(),
      teeth = 24
    for (let i = 0; i <= teeth * 4; i++) {
      const angle = (i / (teeth * 4)) * Math.PI * 2,
        r = radius * (i % 4 === 1 || i % 4 === 2 ? 1 : 0.88)
      if (i === 0) shape.moveTo(Math.cos(angle) * r, Math.sin(angle) * r)
      else shape.lineTo(Math.cos(angle) * r, Math.sin(angle) * r)
    }
    shape.closePath()
    const hole = new THREE.Path()
    hole.absarc(0, 0, radius * 0.2, 0, Math.PI * 2, true)
    shape.holes.push(hole)
    const gear = b.mesh(
      'orrery-clockwork-gear',
      new THREE.ExtrudeGeometry(shape, {
        depth: 0.022,
        bevelEnabled: true,
        bevelThickness: 0.003,
        bevelSize: 0.002,
        bevelSegments: 2,
        steps: 1,
      }),
      b.material('#a98a50', 0.85, 0.32),
      x,
      -0.025,
      z,
      Math.PI / 2,
    )
    gear.castShadow = false
  }
}
