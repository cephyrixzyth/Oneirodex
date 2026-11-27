import * as THREE from 'three'
import { describe, expect, it, vi } from 'vitest'
import { createRoomMaterialLibrary } from './roomMaterials'
import { disposeRoomGroup, beveledBox, batchOwnedStaticGroup } from './roomGeometry'
import { furnishObservatory } from './roomObservatory'
import { createPinballTable } from './pinball/render'

describe('owned observatory material assets', () => {
  it('batches owned static details without moving geometry or consuming interactive meshes', () => {
    const root = new THREE.Group(),
      material = new THREE.MeshStandardMaterial()
    for (const x of [-2, 2]) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), material)
      mesh.position.x = x
      root.add(mesh)
    }
    const control = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 0.2), material)
    control.userData.action = '@keep'
    root.add(control)
    root.updateMatrixWorld(true)
    const before = new THREE.Box3().setFromObject(root)
    batchOwnedStaticGroup(root)
    expect(root.children).toHaveLength(2)
    expect(root.children).toContain(control)
    root.updateMatrixWorld(true)
    const after = new THREE.Box3().setFromObject(root)
    expect(after.min.distanceTo(before.min)).toBeLessThan(0.00001)
    expect(after.max.distanceTo(before.max)).toBeLessThan(0.00001)
    const dispose = vi.spyOn(material, 'dispose')
    disposeRoomGroup(root)
    expect(dispose).toHaveBeenCalledOnce()
  })
  it('shares one scene-owned walnut set between furniture and cabinet until the scene releases it', () => {
    const palette = createRoomMaterialLibrary(() => new THREE.Texture())
    const room = furnishObservatory(new THREE.Scene(), palette)
    const table = createPinballTable(palette)
    const desk = room.group.getObjectByName('reading-desk') as THREE.Mesh
    const cabinet = table.group.getObjectByName('pinball-cabinet') as THREE.Mesh
    expect(desk.material).toBe(cabinet.material)
    const dispose = vi.spyOn(palette.surface('walnut').map!, 'dispose')
    table.dispose()
    room.dispose()
    expect(dispose).not.toHaveBeenCalled()
    palette.dispose()
    palette.dispose()
    expect(dispose).toHaveBeenCalledOnce()
  })

  it('downsamples Low maps once, restores full resolution, and discards late detached images', () => {
    const pending: (() => void)[] = []
    const textures: THREE.Texture[] = []
    const resize = vi.fn(() => ({ width: 512, height: 512 }))
    const palette = createRoomMaterialLibrary((_url, done) => {
      const texture = new THREE.Texture()
      textures.push(texture)
      pending.push(() => {
        texture.image = { width: 1024, height: 1024 }
        done(texture)
      })
      return texture
    }, resize)
    const material = palette.surface('walnut')
    palette.setQuality('low')
    pending[0]()
    expect((material.map!.image as { width: number }).width).toBe(512)
    palette.setQuality('standard')
    expect((material.map!.image as { width: number }).width).toBe(1024)
    palette.setQuality('low')
    expect(resize).toHaveBeenCalledTimes(1)
    const dispose = vi.spyOn(textures[1], 'dispose')
    palette.dispose()
    pending[1]()
    expect(textures[1].image).toBeNull()
    expect(dispose).toHaveBeenCalledOnce()
  })
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
