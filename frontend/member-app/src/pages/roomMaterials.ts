import * as THREE from 'three'

export type RoomSurface = 'walnut' | 'floor' | 'velvet'
const ROOT = '/static/newstyle/rooms/aurora/materials/'

/** Per-world public art resources. The owning scene group disposes these maps. */
export function createRoomMaterialLibrary(
  load: (url: string) => THREE.Texture = (url) => new THREE.TextureLoader().load(url),
) {
  const surfaces = new Map<RoomSurface, THREE.MeshStandardMaterial>()
  const solids = new Map<string, THREE.MeshStandardMaterial>()
  function surface(role: RoomSurface) {
    let found = surfaces.get(role)
    if (found) return found
    function texture(kind: string, color = false) {
      const value = load(ROOT + role + '-' + kind + '.jpg')
      value.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace
      value.wrapS = value.wrapT = THREE.RepeatWrapping
      value.anisotropy = 4
      value.repeat.setScalar(role === 'floor' ? 3 : role === 'velvet' ? 2 : 1)
      return value
    }
    found = new THREE.MeshStandardMaterial({
      name: 'aurora-' + role,
      color: role === 'velvet' ? '#275b47' : role === 'walnut' ? '#c4af99' : '#baa58e',
      map: texture('color', true),
      normalMap: texture('normal'),
      roughnessMap: texture('roughness'),
      roughness: role === 'velvet' ? 0.95 : 0.72,
      normalScale: new THREE.Vector2(
        role === 'velvet' ? 0.22 : 0.32,
        role === 'velvet' ? 0.22 : 0.32,
      ),
    })
    if (role === 'velvet') {
      found.onBeforeCompile = (shader) => {
        shader.fragmentShader = shader.fragmentShader.replace(
          '#include <map_fragment>',
          `#include <map_fragment>
          #ifdef USE_MAP
            float clothLight=clamp(dot(sampledDiffuseColor.rgb,vec3(0.2126,0.7152,0.0722))*4.0,0.0,1.0);
            diffuseColor.rgb=diffuse*mix(0.65,1.15,clothLight);
          #endif`,
        )
      }
      found.customProgramCacheKey = () => 'aurora-emerald-velvet-v1'
    }
    surfaces.set(role, found)
    return found
  }
  function material(color: string, metalness = 0, roughness = 0.65, glow = 0) {
    if (!metalness && !glow) {
      if (['#69442e', '#38271f', '#765039', '#573b2e'].includes(color)) return surface('walnut')
      if (color === '#164938') return surface('velvet')
    }
    const key = [color, metalness, roughness, glow].join(':')
    let found = solids.get(key)
    if (!found) {
      found = new THREE.MeshStandardMaterial({
        color,
        metalness,
        roughness: metalness > 0.5 ? Math.min(roughness, 0.32) : roughness,
        emissive: glow ? new THREE.Color(color) : new THREE.Color(0),
        emissiveIntensity: glow,
      })
      solids.set(key, found)
    }
    return found
  }
  return { surface, material }
}
