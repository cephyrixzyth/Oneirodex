import * as THREE from 'three'
import { describe, expect, it, vi } from 'vitest'
import { createRoomMaterialLibrary } from './roomMaterials'
import { disposeRoomGroup, beveledBox } from './roomGeometry'

describe('owned observatory material assets', () => {
  it('keeps furniture UVs normalized so scanned material scale does not depend on raw world coordinates', () => {
    const geometry = beveledBox(2, 3, 4, 0.08)
    const uv = geometry.getAttribute('uv')
    for (let i = 0; i < uv.count; i++) {
      expect(uv.getX(i)).toBeGreaterThanOrEqual(0)
      expect(uv.getX(i)).toBeLessThanOrEqual(1)
      expect(uv.getY(i)).toBeGreaterThanOrEqual(0)
      expect(uv.getY(i)).toBeLessThanOrEqual(1)
    }
    geometry.dispose()
  })
  it('uses local colour, normal and roughness maps with their correct colour spaces', () => {
    const urls: string[] = []
    const library = createRoomMaterialLibrary((url) => {
      urls.push(url)
      return new THREE.Texture()
    })
    const material = library.surface('walnut')
    expect(material.map?.colorSpace).toBe(THREE.SRGBColorSpace)
    expect(material.normalMap?.colorSpace).toBe(THREE.NoColorSpace)
    expect(material.roughnessMap?.colorSpace).toBe(THREE.NoColorSpace)
    expect(urls).toHaveLength(3)
    expect(urls.every((url) => url.startsWith('/static/newstyle/rooms/aurora/materials/'))).toBe(
      true,
    )
    for (const texture of [material.map!, material.normalMap!, material.roughnessMap!]) {
      expect(texture.wrapS).toBe(THREE.RepeatWrapping)
      expect(texture.anisotropy).toBeLessThanOrEqual(4)
    }
    expect(library.surface('walnut')).toBe(material)
  })

  it('owns textured materials per world and disposes every shared map once', () => {
    const load = () => new THREE.Texture()
    const library = createRoomMaterialLibrary(load)
    const other = createRoomMaterialLibrary(load)
    const material = library.surface('velvet')
    expect(other.surface('velvet')).not.toBe(material)
    const calls = [material.map!, material.normalMap!, material.roughnessMap!].map((texture) =>
      vi.spyOn(texture, 'dispose'),
    )
    const root = new THREE.Group()
    root.add(
      new THREE.Mesh(new THREE.BoxGeometry(), material),
      new THREE.Mesh(new THREE.BoxGeometry(), material),
    )
    disposeRoomGroup(root)
    disposeRoomGroup(root)
    calls.forEach((call) => expect(call).toHaveBeenCalledOnce())
  })
})
