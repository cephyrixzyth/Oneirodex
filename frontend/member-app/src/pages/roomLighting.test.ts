import * as THREE from 'three'
import { expect, it, vi } from 'vitest'
import { ownRoomEnvironment } from './roomLighting'

it('cleans the owned reflection target once without removing a replacement environment', () => {
  const scene = new THREE.Scene()
  const target = new THREE.WebGLRenderTarget(16, 16)
  const dispose = vi.spyOn(target, 'dispose')
  const release = ownRoomEnvironment(scene, target)
  expect(scene.environment).toBe(target.texture)
  const replacement = new THREE.Texture()
  scene.environment = replacement
  release()
  release()
  expect(dispose).toHaveBeenCalledOnce()
  expect(scene.environment).toBe(replacement)
})
