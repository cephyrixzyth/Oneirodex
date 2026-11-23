import * as THREE from 'three'
import { roomBuilder } from '../roomGeometry'
import type { createRoomMaterialLibrary } from '../roomMaterials'

/** Original cabinet joinery and engraved playfield, outside the simulation boundary. */
export function detailPinballCabinet(
  group: THREE.Group,
  materials: ReturnType<typeof createRoomMaterialLibrary>,
) {
  const b = roomBuilder(group, materials.material)
  const brass = '#c9a96b'
  const art = new THREE.TextureLoader().load('/static/newstyle/rooms/aurora/moonfall-playfield.svg')
  art.colorSpace = THREE.SRGBColorSpace
  art.anisotropy = 4
  const surface = new THREE.Mesh(
    new THREE.PlaneGeometry(1.38, 2.9),
    new THREE.MeshPhysicalMaterial({
      map: art,
      color: new THREE.Color('#e6eee3'),
      roughness: 0.36,
      metalness: 0.08,
      clearcoat: 0.55,
      clearcoatRoughness: 0.22,
    }),
  )
  surface.name = 'pinball-engraved-playfield'
  surface.rotation.x = -Math.PI / 2 + Math.atan(0.035 / 0.72)
  surface.position.y = 1.036
  surface.receiveShadow = true
  group.add(surface)
  for (const side of [-1, 1]) {
    for (const y of [0.57, 0.8])
      b.box('cabinet-raised-moulding', 0.025, 0.025, 2.92, side * 0.843, y, 0, brass, 0.8, 0.008)
    b.box('cabinet-side-panel', 0.025, 0.17, 2.77, side * 0.834, 0.68, 0, '#38271f', 0, 0.025)
    b.box('cabinet-side-lower-beading', 0.035, 0.028, 3.12, side * 0.84, 0.52, 0, brass, 0.7, 0.01)
    b.box('cabinet-side-veneer', 0.028, 0.11, 2.62, side * 0.853, 0.68, 0, '#69442e', 0, 0.025)
    for (const z of [-1.3, -0.75, 0, 0.75, 1.3]) {
      const head = b.mesh(
        'cabinet-metal-stud',
        new THREE.SphereGeometry(0.016, 8, 6),
        b.material(brass, 0.9, 0.25),
        side * 0.861,
        0.81,
        z,
      )
      head.scale.x = 0.45
    }
    b.box(
      'cabinet-backboard-upright',
      0.065,
      1.13,
      0.06,
      side * 0.77,
      1.64,
      -1.565,
      brass,
      0.75,
      0.018,
    )
    b.box(
      'cabinet-backboard-top-inlay',
      0.06,
      0.035,
      0.035,
      side * 0.78,
      2.2,
      -1.55,
      brass,
      0.75,
      0.009,
    )
  }
  b.box('cabinet-score-surround-top', 1.51, 0.024, 0.04, 0, 1.96, -1.548, brass, 0.75, 0.008)
  b.box('cabinet-score-surround-bottom', 1.51, 0.024, 0.04, 0, 1.485, -1.548, brass, 0.75, 0.008)
  b.box('cabinet-front-lacquer', 1.5, 0.29, 0.04, 0, 0.73, 1.651, '#38271f', 0, 0.03)
  b.box('cabinet-front-plaque', 0.52, 0.12, 0.024, 0, 0.73, 1.68, brass, 0.7, 0.025)
  for (const side of [-1, 1])
    b.mesh(
      'cabinet-front-medallion',
      new THREE.TorusGeometry(0.072, 0.009, 6, 24),
      b.material(brass, 0.85, 0.24),
      side * 0.57,
      0.72,
      1.68,
    )
  const shadowData = new Uint8Array(64 * 64 * 4)
  for (let y = 0; y < 64; y++)
    for (let x = 0; x < 64; x++) {
      const radius = Math.hypot((x - 31.5) / 32, (y - 31.5) / 32)
      const index = (y * 64 + x) * 4
      shadowData[index + 3] = Math.round(Math.max(0, 1 - radius) ** 1.5 * 170)
    }
  const shadowTexture = new THREE.DataTexture(shadowData, 64, 64)
  shadowTexture.needsUpdate = true
  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(2.5, 4.2),
    new THREE.MeshBasicMaterial({ map: shadowTexture, transparent: true, depthWrite: false }),
  )
  shadow.name = 'pinball-ground-contact'
  shadow.rotation.x = -Math.PI / 2
  shadow.position.y = 0.012
  group.add(shadow)
}
