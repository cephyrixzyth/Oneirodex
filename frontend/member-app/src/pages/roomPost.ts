import * as THREE from 'three'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { GTAOPass } from 'three/examples/jsm/postprocessing/GTAOPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js'

export type RoomQuality = 'low' | 'standard' | 'high'
export const ROOM_QUALITIES: readonly RoomQuality[] = ['low', 'standard', 'high']

/** Pixel-ratio ceiling for each tier; the device ratio still wins when lower. */
export function roomPixelRatio(quality: RoomQuality, device = 1) {
  return Math.min(device || 1, quality === 'low' ? 0.6 : quality === 'high' ? 1.6 : 1.3)
}

/** What each tier turns on. Low draws straight to the screen like before. */
export function roomEffects(quality: RoomQuality) {
  return {
    composer: quality !== 'low',
    bloom: quality !== 'low',
    msaa: quality === 'high' ? 4 : quality === 'standard' ? 2 : 0,
    ambientOcclusion: quality === 'high',
  }
}

// A gentle lens falloff, applied after tone mapping in display space.
const VignetteShader = {
  name: 'RoomVignette',
  uniforms: { tDiffuse: { value: null }, strength: { value: 0.32 } },
  vertexShader:
    'varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
  fragmentShader: `
    uniform sampler2D tDiffuse; uniform float strength; varying vec2 vUv;
    void main(){
      vec4 color=texture2D(tDiffuse,vUv);
      vec2 d=vUv-.5; float v=1.-strength*smoothstep(.25,.85,dot(d,d)*2.2);
      gl_FragColor=vec4(color.rgb*v,color.a);
    }`,
}

/**
 * Post-processing for the library rooms: MSAA, bloom on light sources, and
 * ground-truth ambient occlusion on High. XR sessions always bypass it, since
 * headsets render each eye directly and are the most frame-time sensitive.
 */
export function createRoomPost(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  camera: THREE.PerspectiveCamera,
) {
  let quality: RoomQuality = 'standard'
  let composer: EffectComposer | null = null
  let ao: GTAOPass | null = null
  let width = 1,
    height = 1
  function release() {
    composer?.passes.forEach((pass) => pass.dispose())
    composer?.dispose()
    composer = null
    ao = null
  }
  function build() {
    release()
    const effects = roomEffects(quality)
    if (!effects.composer) return
    const target = new THREE.WebGLRenderTarget(1, 1, {
      type: THREE.HalfFloatType,
      samples: effects.msaa,
    })
    composer = new EffectComposer(renderer, target)
    composer.setPixelRatio(renderer.getPixelRatio())
    composer.setSize(width, height)
    composer.addPass(new RenderPass(scene, camera))
    if (effects.ambientOcclusion) {
      ao = new GTAOPass(scene, camera, width, height)
      ao.updateGtaoMaterial({
        radius: 0.4,
        distanceExponent: 1.6,
        thickness: 1,
        scale: 1.1,
        samples: 16,
      })
      ao.updatePdMaterial({
        lumaPhi: 10,
        depthPhi: 2,
        normalPhi: 3,
        radius: 6,
        rings: 2,
        samples: 16,
      })
      ao.blendIntensity = 0.85
      composer.addPass(ao)
    }
    if (effects.bloom)
      // Threshold well above 1 in linear light: only lamps, screens and glowing trim bloom.
      composer.addPass(new UnrealBloomPass(new THREE.Vector2(width, height), 0.32, 0.5, 1.6))
    composer.addPass(new OutputPass())
    composer.addPass(new ShaderPass(VignetteShader))
  }
  build()
  return {
    get quality() {
      return quality
    },
    get active() {
      return Boolean(composer)
    },
    setQuality(next: RoomQuality) {
      if (next === quality) return
      quality = next
      build()
    },
    setSize(nextWidth: number, nextHeight: number) {
      width = Math.max(1, nextWidth)
      height = Math.max(1, nextHeight)
      if (!composer) return
      composer.setPixelRatio(renderer.getPixelRatio())
      composer.setSize(width, height)
    },
    render() {
      if (!composer || renderer.xr.isPresenting) renderer.render(scene, camera)
      else composer.render()
    },
    dispose: release,
  }
}
