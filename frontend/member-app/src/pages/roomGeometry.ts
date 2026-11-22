import * as THREE from 'three'

/** Original rounded furniture profiles; no model download or renderer required. */
export function beveledBox(width: number, height: number, depth: number, rounding = 0.035) {
  const r = Math.min(rounding, width / 4, height / 4, depth / 4)
  const x = -width / 2,
    y = -height / 2
  const shape = new THREE.Shape()
  shape.moveTo(x + r, y)
  shape.lineTo(x + width - r, y)
  shape.quadraticCurveTo(x + width, y, x + width, y + r)
  shape.lineTo(x + width, y + height - r)
  shape.quadraticCurveTo(x + width, y + height, x + width - r, y + height)
  shape.lineTo(x + r, y + height)
  shape.quadraticCurveTo(x, y + height, x, y + height - r)
  shape.lineTo(x, y + r)
  shape.quadraticCurveTo(x, y, x + r, y)
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: Math.max(0.001, depth - r * 2),
    bevelEnabled: true,
    bevelThickness: r,
    bevelSize: r * 0.4,
    bevelSegments: 2,
    steps: 1,
    curveSegments: 4,
  })
  geometry.center()
  return geometry
}

export function roomBuilder(root: THREE.Group) {
  const materials = new Map<string, THREE.MeshStandardMaterial>()
  const geometry = new Map<string, THREE.BufferGeometry>()
  function material(color: string, metalness = 0, roughness = 0.65, glow = 0) {
    const key = [color, metalness, roughness, glow].join(':')
    let found = materials.get(key)
    if (!found) {
      found = new THREE.MeshStandardMaterial({
        color,
        metalness,
        roughness,
        emissive: glow ? new THREE.Color(color) : new THREE.Color(0),
        emissiveIntensity: glow,
      })
      materials.set(key, found)
    }
    return found
  }
  function mesh(
    name: string,
    geo: THREE.BufferGeometry,
    mat: THREE.Material,
    x = 0,
    y = 0,
    z = 0,
    rx = 0,
    ry = 0,
    rz = 0,
  ) {
    const item = new THREE.Mesh(geo, mat)
    item.name = name
    item.position.set(x, y, z)
    item.rotation.set(rx, ry, rz)
    item.castShadow = true
    item.receiveShadow = true
    root.add(item)
    return item
  }
  function box(
    name: string,
    w: number,
    h: number,
    d: number,
    x: number,
    y: number,
    z: number,
    color: string,
    metal = 0,
    rounding = 0.035,
  ) {
    const key = [w, h, d, rounding].join(':')
    if (!geometry.has(key)) geometry.set(key, beveledBox(w, h, d, rounding))
    return mesh(name, geometry.get(key)!, material(color, metal), x, y, z)
  }
  function strut(
    name: string,
    from: THREE.Vector3,
    to: THREE.Vector3,
    radius: number,
    color: string,
  ) {
    const delta = to.clone().sub(from)
    const item = mesh(
      name,
      new THREE.CylinderGeometry(radius, radius, delta.length(), 10),
      material(color, 0.65, 0.32),
    )
    item.position.copy(from).add(to).multiplyScalar(0.5)
    item.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize())
    return item
  }
  return { material, mesh, box, strut }
}

const cleaned = new WeakSet<THREE.Group>()
export function disposeRoomGroup(root: THREE.Group) {
  if (cleaned.has(root)) return
  cleaned.add(root)
  root.removeFromParent()
  const geometries = new Set<THREE.BufferGeometry>()
  const materials = new Set<THREE.Material>()
  const textures = new Set<THREE.Texture>()
  root.traverse((item) => {
    if (item instanceof THREE.InstancedMesh) item.dispose()
    if (item instanceof THREE.Mesh || item instanceof THREE.Line || item instanceof THREE.Points) {
      geometries.add(item.geometry)
      for (const mat of Array.isArray(item.material) ? item.material : [item.material])
        materials.add(mat)
    }
    if (item instanceof THREE.DirectionalLight || item instanceof THREE.PointLight)
      item.shadow.dispose()
  })
  for (const mat of materials) {
    for (const value of Object.values(mat)) if (value instanceof THREE.Texture) textures.add(value)
    mat.dispose()
  }
  textures.forEach((texture) => texture.dispose())
  geometries.forEach((geometry) => geometry.dispose())
  root.clear()
}
