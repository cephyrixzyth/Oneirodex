import * as THREE from 'three'

/**
 * Procedural surface detail for the themed rooms. Everything is generated from
 * seeded noise into DataTextures, so there is nothing to download and it runs
 * the same in tests (no 2D canvas needed).
 */
export type ProceduralFinish = 'plaster' | 'panel' | 'lacquer' | 'carpet'

const SIZE = 256

function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0
    return s / 4294967296
  }
}

/** Tileable value-noise fBm on a SIZE×SIZE grid, 0..1. */
function fbm(seed: number, baseCells: number, octaves: number, gain = 0.5) {
  const out = new Float32Array(SIZE * SIZE)
  const random = rng(seed)
  let amplitude = 1,
    total = 0
  for (let o = 0; o < octaves; o++) {
    const cells = baseCells << o
    const lattice = new Float32Array(cells * cells)
    for (let i = 0; i < lattice.length; i++) lattice[i] = random()
    for (let y = 0; y < SIZE; y++) {
      const fy = (y / SIZE) * cells,
        y0 = Math.floor(fy),
        ty = fy - y0,
        sy = ty * ty * (3 - 2 * ty)
      for (let x = 0; x < SIZE; x++) {
        const fx = (x / SIZE) * cells,
          x0 = Math.floor(fx),
          tx = fx - x0,
          sx = tx * tx * (3 - 2 * tx)
        const at = (cx: number, cy: number) => lattice[(cy % cells) * cells + (cx % cells)]
        const top = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * sx
        const bottom = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * sx
        out[y * SIZE + x] += (top + (bottom - top) * sy) * amplitude
      }
    }
    total += amplitude
    amplitude *= gain
  }
  for (let i = 0; i < out.length; i++) out[i] /= total
  return out
}

function heightField(kind: ProceduralFinish) {
  if (kind === 'plaster') {
    // Broad trowel swells with fine sand grit.
    const broad = fbm(11, 4, 3),
      grit = fbm(29, 64, 2)
    return broad.map((v, i) => v * 0.5 + grit[i] * 0.2)
  }
  if (kind === 'carpet') {
    const pile = fbm(41, 128, 1),
      mottling = fbm(43, 8, 2)
    return pile.map((v, i) => v * 0.7 + mottling[i] * 0.3)
  }
  if (kind === 'lacquer') {
    // Barely-there orange peel.
    return fbm(53, 32, 2).map((v) => v * 0.12)
  }
  // Panel: a 2×2 grid of floor/deck plates with recessed seams and wear.
  const wear = fbm(67, 16, 3)
  const height = new Float32Array(SIZE * SIZE)
  const plate = SIZE / 2
  for (let y = 0; y < SIZE; y++)
    for (let x = 0; x < SIZE; x++) {
      const dx = Math.min(x % plate, plate - (x % plate)),
        dy = Math.min(y % plate, plate - (y % plate))
      const seam = Math.min(1, Math.min(dx, dy) / 3)
      height[y * SIZE + x] = seam * 0.9 + wear[y * SIZE + x] * 0.04
    }
  return height
}

function packNormals(height: Float32Array, strength: number) {
  const data = new Uint8Array(SIZE * SIZE * 4)
  const h = (x: number, y: number) => height[((y + SIZE) % SIZE) * SIZE + ((x + SIZE) % SIZE)]
  for (let y = 0; y < SIZE; y++)
    for (let x = 0; x < SIZE; x++) {
      const nx = (h(x - 1, y) - h(x + 1, y)) * strength,
        ny = (h(x, y + 1) - h(x, y - 1)) * strength
      const length = Math.hypot(nx, ny, 1)
      const o = (y * SIZE + x) * 4
      data[o] = Math.round(((nx / length) * 0.5 + 0.5) * 255)
      data[o + 1] = Math.round(((ny / length) * 0.5 + 0.5) * 255)
      data[o + 2] = Math.round(((1 / length) * 0.5 + 0.5) * 255)
      data[o + 3] = 255
    }
  return data
}

function packGray(values: Float32Array, low: number, high: number) {
  const data = new Uint8Array(SIZE * SIZE * 4)
  for (let i = 0; i < values.length; i++) {
    const v = Math.round(Math.min(1, Math.max(0, low + (high - low) * values[i])) * 255)
    data.set([v, v, v, 255], i * 4)
  }
  return data
}

function dataTexture(data: Uint8Array, color = false) {
  const texture = new THREE.DataTexture(data, SIZE, SIZE)
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping
  texture.magFilter = THREE.LinearFilter
  texture.minFilter = THREE.LinearMipmapLinearFilter
  texture.generateMipmaps = true
  texture.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace
  texture.anisotropy = 4
  texture.needsUpdate = true
  return texture
}

const recipe: Record<
  ProceduralFinish,
  { strength: number; rough: [number, number]; albedo: [number, number] }
> = {
  plaster: { strength: 3, rough: [0.8, 0.95], albedo: [0.9, 1] },
  panel: { strength: 12, rough: [0.62, 0.4], albedo: [0.7, 1] },
  lacquer: { strength: 0.8, rough: [0.3, 0.42], albedo: [0.97, 1] },
  carpet: { strength: 10, rough: [0.92, 1], albedo: [0.8, 1] },
}

/** A material finish tinted to `color`. Textures are owned by the material. */
export function proceduralMaterial(
  kind: ProceduralFinish,
  color: string,
  metalness = 0,
  tileMeters = 1,
) {
  const height = heightField(kind)
  const { strength, rough, albedo } = recipe[kind]
  const normalMap = dataTexture(packNormals(height, strength))
  const roughnessMap = dataTexture(packGray(height, rough[0], rough[1]))
  const map = dataTexture(packGray(height, albedo[0], albedo[1]), true)
  for (const texture of [normalMap, roughnessMap, map]) texture.repeat.setScalar(1 / tileMeters)
  const material = new THREE.MeshStandardMaterial({
    name: 'procedural-' + kind,
    color,
    metalness,
    roughness: 1,
    map,
    normalMap,
    roughnessMap,
    normalScale: new THREE.Vector2(0.6, 0.6),
  })
  material.userData.boxProjected = true
  return material
}

/**
 * Replace a geometry's UVs with box-projected coordinates in metres, so tiled
 * textures keep a constant physical scale whatever the size of the mesh.
 */
export function boxProjectUVs(geometry: THREE.BufferGeometry) {
  if (geometry.userData.boxProjected) return
  const position = geometry.getAttribute('position'),
    normal = geometry.getAttribute('normal')
  if (!position || !normal) return
  const uv = new Float32Array(position.count * 2)
  for (let i = 0; i < position.count; i++) {
    const ax = Math.abs(normal.getX(i)),
      ay = Math.abs(normal.getY(i)),
      az = Math.abs(normal.getZ(i))
    const x = position.getX(i),
      y = position.getY(i),
      z = position.getZ(i)
    if (ay >= ax && ay >= az) uv.set([x, z], i * 2)
    else if (ax >= az) uv.set([z, y], i * 2)
    else uv.set([x, y], i * 2)
  }
  geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2))
  geometry.userData.boxProjected = true
}

/** Box-project every mesh under `root` whose material asks for it. */
export function projectTexturedMeshes(root: THREE.Object3D) {
  root.traverse((item) => {
    if (!(item instanceof THREE.Mesh) || Array.isArray(item.material)) return
    if (item.material.userData?.boxProjected) boxProjectUVs(item.geometry)
  })
}
