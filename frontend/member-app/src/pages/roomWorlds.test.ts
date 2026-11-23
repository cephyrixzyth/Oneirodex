import * as THREE from 'three'
import { expect, it, vi } from 'vitest'
import { buildThemedRoom, themedWorlds } from './roomWorlds'

it.each([
  ['afterglow', 'arcade-cabinet'],
  ['monochrome', 'drafting-arm'],
  ['greenhouse', 'planting-trough'],
  ['signal', 'oscilloscope'],
  ['tape-deck', 'tape-reel'],
  ['deep-space', 'observation-rib'],
  ['tideglass', 'pressure-porthole'],
] as const)(
  'builds %s with its own physical focal object and an unobstructed catalog aisle',
  (slug, fixture) => {
    const scene = new THREE.Scene()
    const room = buildThemedRoom(scene, slug)!
    expect(themedWorlds).toHaveProperty(slug)
    expect(room.group.getObjectByName(fixture)).toBeDefined()
    expect(room.canStandAt(0, 2.1)).toBe(true)
    expect(room.canStandAt(-2.65, -0.95)).toBe(true)
    expect(room.canStandAt(2.65, -0.95)).toBe(true)
    expect(room.canStandAt(0, -3.8)).toBe(false)
    scene.updateMatrixWorld(true)
    const eye = new THREE.Vector3(0, 1.55, 2.1)
    for (const x of [-2.22, -0.74, 0.74, 2.22]) {
      const center = new THREE.Vector3(x, 1.99, -3.55)
      const delta = center.clone().sub(eye)
      const ray = new THREE.Raycaster(eye, delta.clone().normalize(), 0, delta.length() - 0.002)
      expect(
        ray
          .intersectObject(room.group, true)
          .filter((hit) => hit.object.visible)
          .map((hit) => hit.object.name),
      ).toEqual([])
    }
    const mesh = room.group.getObjectByName('world-floor') as THREE.Mesh
    const dispose = vi.spyOn(mesh.geometry, 'dispose')
    room.dispose()
    room.dispose()
    expect(dispose).toHaveBeenCalledOnce()
    expect(scene.children).toHaveLength(0)
  },
)
