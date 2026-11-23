import * as THREE from 'three'

export type RoomSurface = 'walnut' | 'floor' | 'velvet'
type Quality = 'low' | 'standard' | 'high'
type TextureImage = { width: number; height: number; naturalWidth?: number; naturalHeight?: number }
const ROOT = '/static/newstyle/rooms/aurora/materials/'

/** Per-world public art resources. The owning scene group disposes these maps. */
export function createRoomMaterialLibrary(
  load: (url: string, done: (texture: THREE.Texture) => void) => THREE.Texture = (url, done) =>
    new THREE.TextureLoader().load(url, done),
  resize: (image: TextureImage, maximum: number) => TextureImage = (image, maximum) => {
    const width = image.naturalWidth || image.width,
      height = image.naturalHeight || image.height
    const scale = Math.min(1, maximum / Math.max(width, height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    canvas
      .getContext('2d')!
      .drawImage(image as CanvasImageSource, 0, 0, canvas.width, canvas.height)
    return canvas
  },
) {
  const surfaces = new Map<RoomSurface, THREE.MeshStandardMaterial>()
  const solids = new Map<string, THREE.MeshStandardMaterial>()
  const owned = new Set<THREE.Material>(),
    textures = new Map<string, THREE.Texture>()
  const images = new Map<
    THREE.Texture,
    { full: TextureImage; small: TextureImage | null; maximum: number }
  >()
  let quality: Quality = 'standard',
    disposed = false
  function own<T extends THREE.Material>(value: T) {
    owned.add(value)
    return value
  }
  function apply(texture: THREE.Texture) {
    const record = images.get(texture)
    texture.anisotropy = quality === 'low' ? 2 : 4
    if (!record) return
    if (quality === 'low' && !record.small) record.small = resize(record.full, record.maximum)
    const image = quality === 'low' ? record.small : record.full
    if (texture.image !== image) {
      // WebGL immutable texture storage must be reallocated when dimensions change.
      texture.dispose()
      texture.image = image
      texture.needsUpdate = true
    }
  }
  function publicTexture(url: string, color = false, maximum = 512) {
    if (disposed) throw new Error('Room materials are disposed.')
    if (!url.startsWith('/static/newstyle/rooms/aurora/'))
      throw new Error('Room art must use a local asset.')
    const cached = textures.get(url)
    if (cached) return cached
    const value = load(url, (texture) => {
      if (disposed) {
        texture.image = null
        return
      }
      images.set(texture, { full: texture.image as TextureImage, small: null, maximum })
      apply(texture)
    })
    value.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace
    textures.set(url, value)
    return value
  }
  function setQuality(next: Quality) {
    if (disposed || quality === next) return
    quality = next
    textures.forEach(apply)
    for (const material of owned)
      if (
        material instanceof THREE.MeshPhysicalMaterial &&
        typeof material.userData.roomClearcoat === 'number'
      ) {
        material.clearcoat = quality === 'low' ? 0 : material.userData.roomClearcoat
        material.needsUpdate = true
      }
  }
  function dispose() {
    if (disposed) return
    disposed = true
    owned.forEach((material) => material.dispose())
    textures.forEach((texture) => {
      texture.dispose()
      texture.image = null
    })
    images.clear()
    textures.clear()
    owned.clear()
    surfaces.clear()
    solids.clear()
  }
  function surface(role: RoomSurface) {
    if (disposed) throw new Error('Room materials are disposed.')
    let found = surfaces.get(role)
    if (found) return found
    function texture(kind: string, color = false) {
      const value = publicTexture(ROOT + role + '-' + kind + '.jpg', color)
      value.wrapS = value.wrapT = THREE.RepeatWrapping
      value.anisotropy = quality === 'low' ? 2 : 4
      value.repeat.setScalar(role === 'floor' ? 3 : role === 'velvet' ? 2 : 1)
      return value
    }
    found = own(
      new THREE.MeshStandardMaterial({
        name: 'aurora-' + role,
        color: role === 'velvet' ? '#214c38' : role === 'walnut' ? '#a18b74' : '#8c765f',
        map: texture('color', true),
        normalMap: texture('normal'),
        roughnessMap: texture('roughness'),
        roughness: role === 'velvet' ? 0.95 : 0.72,
        normalScale: new THREE.Vector2(
          role === 'velvet' ? 0.22 : 0.32,
          role === 'velvet' ? 0.22 : 0.32,
        ),
      }),
    )
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
    if (disposed) throw new Error('Room materials are disposed.')
    if (!metalness && !glow) {
      if (['#69442e', '#38271f', '#765039', '#573b2e'].includes(color)) return surface('walnut')
      if (color === '#164938') return surface('velvet')
    }
    const key = [color, metalness, roughness, glow].join(':')
    let found = solids.get(key)
    if (!found) {
      const brass =
        metalness > 0.5 && ['#c9a96b', '#a98a50', '#a28a58', '#ac935a', '#96784a'].includes(color)
      found = own(
        new THREE.MeshStandardMaterial({
          color: brass ? new THREE.Color('#9b753f') : new THREE.Color(color),
          metalness: brass ? 0.88 : metalness,
          roughness: brass ? 0.4 : metalness > 0.5 ? Math.min(roughness, 0.32) : roughness,
          emissive: glow ? new THREE.Color(color) : new THREE.Color(0),
          emissiveIntensity: glow,
        }),
      )
      solids.set(key, found)
    }
    return found
  }
  return { surface, material, publicTexture, own, owned, setQuality, dispose }
}
