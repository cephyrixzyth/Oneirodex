import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'

export function ownRoomEnvironment(scene: THREE.Scene, target: THREE.WebGLRenderTarget) {
  scene.environment = target.texture
  scene.environmentIntensity = 0.7
  let disposed = false
  return () => {
    if (disposed) return
    disposed = true
    if (scene.environment === target.texture) scene.environment = null
    target.dispose()
  }
}

/** One prefiltered neutral interior probe: metal/glass highlights without live cube renders. */
export function createObservatoryLighting(renderer: THREE.WebGLRenderer, scene: THREE.Scene) {
  const generator = new THREE.PMREMGenerator(renderer)
  const environment = new RoomEnvironment()
  try {
    return ownRoomEnvironment(scene, generator.fromScene(environment, 0.06, 0.1, 30, { size: 128 }))
  } finally {
    environment.dispose()
    generator.dispose()
  }
}
