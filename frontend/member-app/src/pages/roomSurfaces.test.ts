import * as THREE from 'three'
import { expect, it } from 'vitest'
import { boxProjectUVs, proceduralMaterial } from './roomSurfaces'

it('box-projects UVs in metres so tiled finishes keep a physical scale', () => {
  const geometry = new THREE.BoxGeometry(4, 2, 1)
  boxProjectUVs(geometry)
  const uv = geometry.getAttribute('uv'),
    normal = geometry.getAttribute('normal')
  let spanX = 0
  for (let i = 0; i < uv.count; i++)
    if (Math.abs(normal.getZ(i)) > 0.9) spanX = Math.max(spanX, Math.abs(uv.getX(i)))
  expect(spanX).toBeCloseTo(2)
  expect(geometry.userData.boxProjected).toBe(true)
})

it.each(['plaster', 'panel', 'lacquer', 'carpet'] as const)(
  'builds a tinted %s finish from generated maps',
  (kind) => {
    const material = proceduralMaterial(kind, '#336699', 0, 2)
    expect(material.color.getHexString()).toBe('336699')
    expect(material.normalMap).toBeInstanceOf(THREE.DataTexture)
    expect(material.roughnessMap!.repeat.x).toBeCloseTo(0.5)
    expect(material.userData.boxProjected).toBe(true)
  },
)
