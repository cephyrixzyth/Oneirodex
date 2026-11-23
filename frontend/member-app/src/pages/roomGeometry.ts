import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'

/** Original rounded furniture profiles; no model download or renderer required. */
export function beveledBox(width: number, height: number, depth: number, rounding = 0.035) {
  const r = Math.min(rounding, width / 4, height / 4, depth / 4)
  return new RoundedBoxGeometry(width, height, depth, 3, r)
}

/** Rounded, slightly compressed upholstery and a curved club-chair back shell. */
export function upholsteredPanel(width: number, height: number, depth: number, back = false) {
  const geometry = new RoundedBoxGeometry(
    width,
    height,
    depth,
    5,
    Math.min(0.12, height / 3, depth / 3),
  )
  const positions = geometry.getAttribute('position'),
    normals = geometry.getAttribute('normal')
  for (let i = 0; i < positions.count; i++) {
    const x = positions.getX(i),
      y = positions.getY(i),
      z = positions.getZ(i),
      normal = new THREE.Vector3().fromBufferAttribute(normals, i)
    if (back) {
      positions.setZ(i, z - 0.1 * (x / (width / 2)) ** 2)
      normal.x += ((0.2 * x) / (width / 2) ** 2) * normal.z
    } else if (normal.y > 0) {
      const fx = Math.max(0, 1 - (x / (width / 2)) ** 2),
        fz = Math.max(0, 1 - (z / (depth / 2)) ** 2)
      positions.setY(i, y - 0.035 * fx * fz * normal.y)
      normal.x -= ((0.07 * x) / (width / 2) ** 2) * fz * normal.y
      normal.z -= ((0.07 * z) / (depth / 2) ** 2) * fx * normal.y
    }
    normal.normalize()
    normals.setXYZ(i, normal.x, normal.y, normal.z)
  }
  geometry.computeBoundingBox()
  geometry.computeBoundingSphere()
  return geometry
}

export function roomBuilder(
  root: THREE.Group,
  resolveMaterial?: (
    color: string,
    metalness: number,
    roughness: number,
    glow: number,
  ) => THREE.MeshStandardMaterial,
) {
  const materials = new Map<string, THREE.MeshStandardMaterial>()
  const geometry = new Map<string, THREE.BufferGeometry>()
  function material(color: string, metalness = 0, roughness = 0.65, glow = 0) {
    if (resolveMaterial) return resolveMaterial(color, metalness, roughness, glow)
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
/** Batch a dedicated static-detail owner; animated, translucent and pickable objects stay separate. */
export function batchOwnedStaticGroup(
  root: THREE.Group,
  preserved: ReadonlySet<string> = new Set(),
) {
  const groups = new Map<string, THREE.Mesh[]>()
  for (const child of root.children) {
    if (
      !(child instanceof THREE.Mesh) ||
      child instanceof THREE.InstancedMesh ||
      Array.isArray(child.material) ||
      child.material.transparent ||
      !child.visible ||
      child.userData.action ||
      preserved.has(child.name)
    )
      continue
    const key = [
      child.material.uuid,
      child.castShadow,
      child.receiveShadow,
      child.renderOrder,
    ].join(':')
    const group = groups.get(key) || []
    group.push(child)
    groups.set(key, group)
  }
  const retired = new Set<THREE.BufferGeometry>()
  let index = 0
  for (const meshes of groups.values()) {
    if (meshes.length < 2) continue
    const transformed = meshes.map((mesh) => {
      mesh.updateMatrix()
      const copy = mesh.geometry.clone().applyMatrix4(mesh.matrix)
      if (!copy.index) return copy
      const flat = copy.toNonIndexed()
      copy.dispose()
      return flat
    })
    const geometry = mergeGeometries(transformed)
    transformed.forEach((copy) => copy.dispose())
    if (!geometry) continue
    const first = meshes[0],
      batch = new THREE.Mesh(geometry, first.material)
    batch.name = 'static-art-batch-' + index++
    batch.castShadow = first.castShadow
    batch.receiveShadow = first.receiveShadow
    batch.renderOrder = first.renderOrder
    batch.userData.sourceNames = meshes.map((mesh) => mesh.name)
    meshes.forEach((mesh) => {
      retired.add(mesh.geometry)
      root.remove(mesh)
    })
    root.add(batch)
  }
  const live = new Set(
    root.children
      .filter((child): child is THREE.Mesh => child instanceof THREE.Mesh)
      .map((mesh) => mesh.geometry),
  )
  retired.forEach((geometry) => {
    if (!live.has(geometry)) geometry.dispose()
  })
}

export function disposeRoomGroup(
  root: THREE.Group,
  preserved: ReadonlySet<THREE.Material> = new Set(),
) {
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
    if (preserved.has(mat)) continue
    for (const value of Object.values(mat)) if (value instanceof THREE.Texture) textures.add(value)
    mat.dispose()
  }
  textures.forEach((texture) => texture.dispose())
  geometries.forEach((geometry) => geometry.dispose())
  root.clear()
}
