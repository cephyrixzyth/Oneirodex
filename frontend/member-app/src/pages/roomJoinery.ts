import * as THREE from 'three'
import { roomBuilder } from './roomGeometry'
import type { createRoomMaterialLibrary } from './roomMaterials'

/** Original architectural profiles, upholstery seams and brass furniture hardware. */
export function addObservatoryJoinery(
  root: THREE.Group,
  palette: ReturnType<typeof createRoomMaterialLibrary>,
) {
  const b = roomBuilder(root, palette.material),
    brass = '#c9a96b',
    wood = '#69442e'
  for (const radius of [5.35, 5.48]) {
    b.mesh(
      'observatory-wall-base-profile',
      new THREE.TorusGeometry(radius, 0.045, 8, 128),
      palette.material(wood, 0, 0.6, 0),
      0,
      0.14,
      0,
      Math.PI / 2,
    )
    b.mesh(
      'observatory-wall-capping',
      new THREE.TorusGeometry(radius, 0.04, 8, 128),
      palette.material(brass, 0.75, 0.3, 0),
      0,
      1.08,
      0,
      Math.PI / 2,
    )
  }
  const wall = b.mesh(
    'observatory-walnut-wainscot',
    new THREE.CylinderGeometry(5.48, 5.48, 0.9, 96, 1, true),
    palette.surface('walnut'),
    0,
    0.57,
    0,
  )
  wall.material = wall.material.clone()
  wall.material.side = THREE.DoubleSide
  for (let i = 0; i < 12; i++) {
    const angle = (i * Math.PI) / 6,
      x = Math.cos(angle) * 5.38,
      z = Math.sin(angle) * 5.38
    b.mesh(
      'observatory-fluted-column',
      new THREE.CylinderGeometry(0.05, 0.07, 3.16, 16),
      palette.material(wood, 0, 0.5, 0),
      x,
      1.7,
      z,
    )
    for (const y of [0.23, 1.08, 3.22])
      b.mesh(
        'observatory-column-collar',
        new THREE.CylinderGeometry(0.085, 0.085, 0.035, 16),
        palette.material(brass, 0.8, 0.24, 0),
        x,
        y,
        z,
      )
  }
  for (const side of [-1, 1]) {
    const x = side * 3.15,
      z = 2.8
    const path = new THREE.CatmullRomCurve3(
      [
        new THREE.Vector3(x - 0.52, 0.64, z + 0.36),
        new THREE.Vector3(x - 0.52, 0.64, z - 0.37),
        new THREE.Vector3(x, 0.64, z - 0.44),
        new THREE.Vector3(x + 0.52, 0.64, z - 0.37),
        new THREE.Vector3(x + 0.52, 0.64, z + 0.36),
        new THREE.Vector3(x, 0.64, z + 0.4),
      ],
      true,
      'centripetal',
    )
    b.mesh(
      'velvet-seat-piping',
      new THREE.TubeGeometry(path, 64, 0.009, 5, true),
      palette.material('#a3a879', 0.1, 0.9, 0),
    )
    for (const dx of [-0.36, 0, 0.36])
      for (const y of [0.81, 1.08]) {
        const button = b.mesh(
          'velvet-tuft-button',
          new THREE.SphereGeometry(0.024, 8, 6),
          palette.surface('velvet'),
          x + dx,
          y,
          z + 0.31,
        )
        button.scale.z = 0.45
      }
    for (const arm of [-0.62, 0.62])
      b.box('chair-walnut-arm-cap', 0.19, 0.045, 0.98, x + arm, 0.895, z, wood, 0, 0.025)
  }
  // Turned brass desk legs and nested edge profiles replace an unsupported slab silhouette.
  for (const z of [-1.8, -0.1]) {
    const profile = [
      new THREE.Vector2(0.085, 0),
      new THREE.Vector2(0.09, 0.04),
      new THREE.Vector2(0.045, 0.13),
      new THREE.Vector2(0.055, 0.6),
      new THREE.Vector2(0.1, 0.77),
    ]
    b.mesh(
      'reading-desk-turned-leg',
      new THREE.LatheGeometry(profile, 24),
      palette.material(brass, 0.75, 0.28, 0),
      -4.53,
      0.04,
      z,
    )
  }
  for (const y of [0.78, 0.91])
    b.box('reading-desk-edge-profile', 1.11, 0.025, 2.35, -4.53, y, -0.95, brass, 0.75, 0.012)
  const rim = b.mesh(
    'orrery-pedestal-reeded-rim',
    new THREE.TorusGeometry(0.42, 0.024, 8, 64),
    palette.material(brass, 0.8, 0.25, 0),
    -3.5,
    1.03,
    2.1,
    Math.PI / 2,
  )
  rim.castShadow = false
}
