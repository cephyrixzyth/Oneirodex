import * as THREE from 'three'

const finishes: Record<
  string,
  { wall: string; wood: string; fabric: string; lamp: string; accent: string }
> = {
  oneirodex: {
    wall: '#163128',
    wood: '#69442e',
    fabric: '#164938',
    lamp: '#ffdc9b',
    accent: '#a6dfbf',
  },
  greenhouse: {
    wall: '#213e31',
    wood: '#9b7253',
    fabric: '#74774d',
    lamp: '#ffdf96',
    accent: '#a6c38b',
  },
  afterglow: {
    wall: '#332039',
    wood: '#613758',
    fabric: '#75385e',
    lamp: '#fa76ac',
    accent: '#6be1e8',
  },
  monochrome: {
    wall: '#4a4c50',
    wood: '#87847d',
    fabric: '#676a75',
    lamp: '#f4efdb',
    accent: '#7f9ee9',
  },
  signal: {
    wall: '#33443c',
    wood: '#a26d45',
    fabric: '#465c53',
    lamp: '#ffc474',
    accent: '#8bcead',
  },
  'tape-deck': {
    wall: '#73442c',
    wood: '#b47b4e',
    fabric: '#c47c53',
    lamp: '#ffe7ad',
    accent: '#c4a3ff',
  },
  tideglass: {
    wall: '#24454e',
    wood: '#887448',
    fabric: '#294b61',
    lamp: '#f2c582',
    accent: '#81e1d2',
  },
  'deep-space': {
    wall: '#253646',
    wood: '#6f7d87',
    fabric: '#475367',
    lamp: '#b6e2ff',
    accent: '#69bfee',
  },
}
export const roomArtSlug = (slug: string) => (Object.hasOwn(finishes, slug) ? slug : 'oneirodex')
export const roomFinish = (slug: string) => finishes[roomArtSlug(slug)]

/** Repeated details share geometry and draw calls, including on standalone headsets. */
export function furnishRoom(scene: THREE.Scene, slug: string) {
  const p = roomFinish(slug)
  const unit = new THREE.BoxGeometry(1, 1, 1)
  const object = new THREE.Object3D()
  const batches = new Map<string, THREE.Matrix4[]>()
  function piece(
    color: string,
    x: number,
    y: number,
    z: number,
    w: number,
    h: number,
    d: number,
    angle = 0,
  ) {
    object.position.set(x, y, z)
    object.rotation.set(0, angle, 0)
    object.scale.set(w, h, d)
    object.updateMatrix()
    let batch = batches.get(color)
    if (!batch) {
      batch = []
      batches.set(color, batch)
    }
    batch.push(object.matrix.clone())
  }
  // Narrow joins and alternating boards give the floor depth at seated eye height.
  for (let i = 0; i < 22; i++) {
    const x = i * 0.5 - 5.25
    for (let j = 0; j < 5; j++)
      piece((i + j) % 3 === 0 ? p.wood : '#635748', x, 0.006, j * 2 - 3, 0.495, 0.013, 1.987)
  }
  piece(p.fabric, 0, 0.02, 0.1, 5.8, 0.018, 3.8)
  for (const x of [-2.78, 2.78]) piece(p.accent, x, 0.032, 0.1, 0.035, 0.01, 3.55)
  for (const z of [-1.65, 1.85]) piece(p.accent, 0, 0.032, z, 5.56, 0.01, 0.035)
  // Insets, a console along the back, a pair of armchairs and three pendant lights.
  piece(p.wood, 0, 0.74, 4.58, 6.9, 0.12, 0.7)
  for (const x of [-3.15, -1.6, 1.6, 3.15]) piece(p.wood, x, 0.35, 4.58, 0.1, 0.7, 0.55)
  for (const x of [-2.2, 2.2]) {
    piece(p.fabric, x, 0.44, 3.25, 1.35, 0.35, 1)
    piece(p.fabric, x, 0.82, 3.68, 1.35, 0.58, 0.22)
    for (const side of [-0.62, 0.62]) piece(p.wood, x + side, 0.56, 3.25, 0.14, 0.54, 1.08)
  }
  for (const x of [-3.3, 0, 3.3]) {
    piece('#3c3c37', x, 4.18, -1.05, 0.035, 0.8, 0.035)
    piece(p.wood, x, 3.8, -1.05, 0.84, 0.18, 0.53)
    piece(p.lamp, x, 3.695, -1.05, 0.76, 0.035, 0.47)
  }
  // Cabinets flank the display. Books and cartridges are instanced by finish.
  for (const side of [-1, 1]) {
    const x = side * 4.4
    for (const y of [0.52, 1.24, 1.96, 2.68, 3.4]) piece(p.wood, x, y, -3.57, 1.3, 0.075, 0.53)
    for (const off of [-0.63, 0.63]) piece(p.wood, x + off, 1.96, -3.57, 0.06, 2.98, 0.53)
    for (let shelf = 0; shelf < 4; shelf++)
      for (let i = 0; i < 8; i++) {
        const h = 0.32 + ((i * 7 + shelf * 3) % 6) * 0.047
        const color = [p.fabric, p.accent, '#805d48', p.wood, '#78847a'][(i + shelf) % 5]
        piece(color, x - 0.52 + i * 0.145, 0.57 + shelf * 0.72 + h / 2, -3.53, 0.122, h, 0.3)
      }
  }
  if (roomArtSlug(slug) === 'greenhouse') {
    for (const x of [-4.25, 4.25]) {
      piece(p.wood, x, 0.36, -2.63, 0.66, 0.7, 0.66)
      piece('#654d32', x, 1.12, -2.63, 0.09, 0.9, 0.09)
      for (let i = 0; i < 12; i++) {
        const a = i * 2.4
        piece(
          i % 2 ? '#49704b' : '#758754',
          x + Math.sin(a) * 0.24,
          1.23 + i * 0.055,
          -2.63 + Math.cos(a) * 0.22,
          0.48,
          0.15,
          0.22,
          a,
        )
      }
    }
  } else if (slug === 'deep-space' || slug === 'signal') {
    for (let i = 0; i < 15; i++)
      piece(i % 3 ? p.accent : p.lamp, -1.3 + i * 0.18, 1.04, 4.35, 0.07, 0.07, 0.08)
  } else if (slug === 'afterglow') {
    for (const x of [-5.2, 5.2])
      for (const z of [0, 2, 4]) piece(p.accent, x, 2, z, 0.08, 2.7, 0.07)
  } else {
    for (const x of [-1, 1]) {
      piece('#302e2b', x, 1.12, 4.58, 0.53, 0.63, 0.36)
      piece(p.accent, x, 1.12, 4.38, 0.24, 0.26, 0.05)
    }
  }
  for (const [color, matrices] of batches) {
    const material = new THREE.MeshStandardMaterial({ color, roughness: 0.9 })
    if (color === p.lamp) {
      material.emissive.set(color)
      material.emissiveIntensity = 0.55
    }
    const mesh = new THREE.InstancedMesh(unit, material, matrices.length)
    matrices.forEach((m, i) => mesh.setMatrixAt(i, m))
    mesh.instanceMatrix.needsUpdate = true
    scene.add(mesh)
  }
}
