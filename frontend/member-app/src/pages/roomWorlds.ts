import * as THREE from 'three'
import {
  batchOwnedStaticGroup,
  disposeRoomGroup,
  roomBuilder,
  upholsteredPanel,
} from './roomGeometry'
import { READING_DISPLAY as desk } from './roomLayout'

type Palette = readonly [
  wall: string,
  floor: string,
  cabinet: string,
  trim: string,
  light: string,
  upholstery: string,
]

export const themedWorlds = {
  afterglow: ['#282532', '#292631', '#352433', '#ad658e', '#72e0da', '#52263d'],
  monochrome: ['#363b3e', '#515557', '#a9a49a', '#67767d', '#f1e3c6', '#41494d'],
  greenhouse: ['#23372b', '#5d4e3c', '#4a3729', '#758a6e', '#f4daa1', '#47634a'],
  signal: ['#212d28', '#393731', '#503c2d', '#737e6a', '#ffbd72', '#495b4d'],
  'tape-deck': ['#382a2b', '#544037', '#654631', '#b4a3d3', '#f7bb86', '#714c70'],
  'deep-space': ['#202d39', '#28323c', '#5b7081', '#97b4c8', '#9ddcff', '#344c66'],
  tideglass: ['#17343b', '#294249', '#3d5c5d', '#9c865d', '#7dd5c9', '#36545b'],
} satisfies Record<string, Palette>

type World = keyof typeof themedWorlds
export const roomArtSlug = (slug: string) =>
  Object.hasOwn(themedWorlds, slug) ? slug : 'oneirodex'
type Footprint = [x: number, z: number, width: number, depth: number]

function surfaceGrain() {
  const pixels = new Uint8Array(64 * 64 * 4)
  let seed = 721
  for (let y = 0; y < 64; y++)
    for (let x = 0; x < 64; x++) {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
      const grain = 206 + ((seed >>> 26) & 31) + (x % 4 === 0 ? 12 : 0)
      const offset = (y * 64 + x) * 4
      pixels.set([grain, grain, grain, 255], offset)
    }
  const map = new THREE.DataTexture(pixels, 64, 64)
  map.wrapS = map.wrapT = THREE.RepeatWrapping
  map.repeat.set(5, 5)
  map.magFilter = THREE.LinearFilter
  map.needsUpdate = true
  return map
}

function backdrop(world: World) {
  const water = world === 'tideglass'
  const garden = world === 'greenhouse'
  return new THREE.ShaderMaterial({
    uniforms: { field: { value: water ? 1 : garden ? 2 : 0 } },
    vertexShader:
      'varying vec2 point; void main(){ point=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
    fragmentShader: `
      uniform int field;
      varying vec2 point;
      float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      void main(){
        vec3 color=vec3(.009,.018,.043);
        if(field==0){
          vec2 cell=point*vec2(252.,107.);
          float star=step(.987,hash(floor(cell)))*exp(-19.*length(fract(cell)-.5));
          float planet=length((point-vec2(.67,-.045))*vec2(1.65,1.));
          float limb=1.-smoothstep(.375,.378,planet);
          color+=star*.9+limb*mix(vec3(.047,.10,.18),vec3(.18,.29,.41),point.y);
          color+=exp(-abs(planet-.379)*240.)*vec3(.1,.26,.4);
        }else if(field==1){
          float beam=max(0.,sin(point.x*33.+point.y*4.));
          float reef=.18+.06*sin(point.x*19.)+.035*sin(point.x*87.);
          color=mix(vec3(.004,.035,.044),vec3(.039,.23,.27),point.y);
          color+=pow(beam,7.)*point.y*.042;
          color*=.18+.82*smoothstep(reef,reef+.035,point.y);
          vec2 cell=point*vec2(162.,82.);
          color+=step(.978,hash(floor(cell)))*exp(-18.*length(fract(cell)-.5))*.18;
        }else{
          float canopy=.37+.1*sin(point.x*13.)+.045*sin(point.x*57.);
          color=mix(vec3(.067,.118,.079),vec3(.23,.32,.26),point.y);
          color*=.32+.68*smoothstep(canopy,canopy+.15,point.y);
        }
        gl_FragColor=vec4(color,1.);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  })
}

function createArcadeCabinet(parent: THREE.Group, x: number, yaw: number, palette: Palette) {
  const cabinet = new THREE.Group()
  cabinet.name = 'arcade-cabinet'
  cabinet.position.set(x, 0, 3.77)
  cabinet.rotation.y = yaw
  parent.add(cabinet)
  const b = roomBuilder(cabinet)
  const shape = new THREE.Shape()
  shape.moveTo(-0.4, 0.04)
  shape.lineTo(0.44, 0.04)
  shape.lineTo(0.44, 0.91)
  shape.lineTo(0.54, 1.02)
  shape.lineTo(0.25, 1.43)
  shape.lineTo(0.29, 1.92)
  shape.quadraticCurveTo(0.24, 2.02, 0.11, 2.02)
  shape.lineTo(-0.4, 2.02)
  shape.closePath()
  const shell = new THREE.ExtrudeGeometry(shape, {
    depth: 0.83,
    bevelSegments: 2,
    bevelSize: 0.025,
    bevelThickness: 0.025,
  })
  shell.translate(0, 0, -0.415)
  b.mesh(
    'laminated-arcade-shell',
    shell,
    b.material(palette[2], 0.04, 0.48),
    0,
    0,
    0,
    0,
    Math.PI / 2,
  )
  b.box('recessed-crt-bezel', 0.68, 0.59, 0.08, 0, 1.47, -0.305, '#121319')
  const screen = b.box(
    'convex-crt-glass',
    0.56,
    0.45,
    0.055,
    0,
    1.47,
    -0.351,
    '#153134',
    0.2,
    0.035,
  )
  if (screen.material instanceof THREE.MeshStandardMaterial) screen.material.roughness = 0.2
  b.mesh(
    'lit-marquee',
    new THREE.BoxGeometry(0.68, 0.18, 0.03),
    b.material(palette[4], 0.04, 0.55, 0.55),
    0,
    1.86,
    -0.314,
  )
  b.box('service-door', 0.51, 0.47, 0.025, 0, 0.47, -0.454, '#191b24')
  b.box('coin-return', 0.11, 0.085, 0.035, 0.1, 0.58, -0.472, '#84838a', 0.75)
  b.mesh(
    'joystick-shaft',
    new THREE.CylinderGeometry(0.013, 0.016, 0.12, 14),
    b.material('#6d747b', 0.85),
    -0.16,
    1.09,
    -0.41,
  )
  b.mesh(
    'joystick-knob',
    new THREE.SphereGeometry(0.043, 16, 10),
    b.material(palette[3]),
    -0.16,
    1.16,
    -0.41,
  )
  for (const offset of [0.09, 0.2]) {
    b.mesh(
      'arcade-action-button',
      new THREE.CylinderGeometry(0.035, 0.04, 0.023, 18),
      b.material(palette[4]),
      offset,
      1.045,
      -0.44,
    )
  }
}

export function buildThemedRoom(scene: THREE.Scene, slug: string) {
  if (!Object.hasOwn(themedWorlds, slug)) return null
  const world = slug as World
  const palette = themedWorlds[world]
  const [wall, floor, cabinet, trim, light, upholstery] = palette
  const root = new THREE.Group()
  root.name = 'room-' + world
  scene.add(root)
  const shell = new THREE.Group()
  root.add(shell)
  const b = roomBuilder(shell)
  const grain = surfaceGrain()
  const floorMaterial = b.material(floor, 0.05, 0.86)
  floorMaterial.map = grain
  b.mesh('world-floor', new THREE.BoxGeometry(11, 0.13, 10), floorMaterial, 0, -0.07, 0)
  b.box('rear-finished-wall', 11, 4.6, 0.15, 0, 2.3, -4.12, wall)
  b.box('entry-finished-wall', 11, 4.6, 0.15, 0, 2.3, 4.95, wall)
  b.box('reading-finished-wall', 0.15, 4.6, 10, -5.45, 2.3, 0, wall)
  const scenic = ['greenhouse', 'deep-space', 'tideglass'].includes(world)
  if (scenic) {
    b.box('window-lower-bulkhead', 0.18, 0.86, 10, 5.44, 0.43, 0, wall)
    b.box('window-upper-bulkhead', 0.18, 0.75, 10, 5.44, 4.225, 0, wall)
    b.mesh(
      'exterior-depth',
      new THREE.PlaneGeometry(15, 3.2),
      backdrop(world),
      5.63,
      2.38,
      0,
      0,
      -Math.PI / 2,
    )
    for (const z of [-4.5, -2.3, -0.1, 2.1, 4.3]) {
      if (world === 'tideglass') {
        const rim = b.mesh(
          'pressure-porthole',
          new THREE.TorusGeometry(1.06, 0.095, 10, 54),
          b.material(trim, 0.67, 0.34),
          5.35,
          2.29,
          z,
          0,
          Math.PI / 2,
        )
        rim.castShadow = false
        for (let i = 0; i < 10; i++) {
          const angle = (i * Math.PI) / 5
          b.mesh(
            'pressure-bolt',
            new THREE.CylinderGeometry(0.03, 0.034, 0.028, 6),
            b.material(trim, 0.7),
            5.218,
            2.29 + Math.sin(angle) * 1.06,
            z + Math.cos(angle) * 1.06,
            0,
            0,
            Math.PI / 2,
          )
        }
      } else {
        b.box(
          world === 'deep-space' ? 'observation-rib' : 'glazing-mullion',
          0.19,
          3.05,
          0.087,
          5.36,
          2.34,
          z,
          trim,
          0.35,
        )
      }
    }
  } else {
    b.box('lounge-finished-wall', 0.15, 4.6, 10, 5.45, 2.3, 0, wall)
    for (let index = 0; index < 11; index++) {
      const z = -4.4 + index * 0.86
      b.box(
        'acoustic-inset',
        0.14,
        2.55,
        0.74,
        5.33,
        2.43,
        z,
        index % 2 ? upholstery : cabinet,
        0,
        0.055,
      )
    }
  }
  if (world === 'greenhouse') {
    const slope = Math.atan2(1.48, 5.43)
    const span = Math.hypot(5.43, 1.48)
    const glass = new THREE.MeshPhysicalMaterial({
      color: new THREE.Color('#a2c4a6'),
      metalness: 0.18,
      roughness: 0.26,
      transparent: true,
      opacity: 0.24,
      side: THREE.DoubleSide,
      depthWrite: false,
    })
    for (const side of [-1, 1]) {
      const pane = b.mesh(
        'pitched-conservatory-roof',
        new THREE.PlaneGeometry(span, 10),
        glass,
        side * 2.715,
        5.32,
        0,
        Math.PI / 2,
      )
      pane.rotateOnWorldAxis(new THREE.Vector3(0, 0, 1), -side * slope)
      pane.castShadow = false
      for (const z of [-4, -2, 0, 2, 4])
        b.strut(
          'pitched-roof-truss',
          new THREE.Vector3(0, 6.06, z),
          new THREE.Vector3(side * 5.43, 4.58, z),
          0.035,
          trim,
        )
    }
  } else {
    b.box('ceiling', 11, 0.16, 10, 0, 4.61, 0, wall)
    for (const z of [-3.5, -0.7, 2.1, 4.4]) {
      if (world === 'deep-space' || world === 'tideglass') {
        const rib = b.mesh(
          'pressure-shell-rib',
          new THREE.TorusGeometry(5.34, 0.09, 8, 48, Math.PI),
          b.material(trim, 0.67, 0.4),
          0,
          0.75,
          z,
        )
        rib.scale.y = 0.69
      } else {
        b.box('ceiling-structural-beam', 10.8, 0.17, 0.21, 0, 4.43, z, cabinet, 0.25)
      }
    }
  }
  if (world === 'afterglow') {
    for (const [y, width] of [
      [2.48, 7.2],
      [2.69, 6.65],
      [2.89, 6.1],
    ]) {
      b.box('stepped-arcade-valance', width, 0.18, 0.26, 0, y, 4.74, cabinet, 0.19)
      b.mesh(
        'arcade-valance-edge',
        new THREE.BoxGeometry(width - 0.12, 0.018, 0.024),
        b.material(light, 0.12, 0.5, 0.4),
        0,
        y - 0.059,
        4.599,
      )
    }
  } else if (world === 'monochrome') {
    for (const x of [-3.4, 0, 3.4]) {
      b.box('workshop-track-light', 0.25, 0.12, 3.35, x, 4.36, 0.35, cabinet, 0.17)
      b.mesh(
        'workshop-strip-diffuser',
        new THREE.BoxGeometry(0.16, 0.022, 3.15),
        b.material(light, 0, 0.61, 0.7),
        x,
        4.29,
        0.35,
      )
    }
  } else if (world === 'signal' || world === 'tape-deck') {
    for (const panelX of [-3.35, 0, 3.35]) {
      b.box('rear-acoustic-absorber', 2.52, 2.0, 0.14, panelX, 2.77, 4.83, upholstery, 0, 0.075)
      for (let slat = 0; slat < 10; slat++)
        b.box(
          'rear-acoustic-slat',
          0.042,
          1.94,
          0.065,
          panelX + (slat - 4.5) * 0.242,
          2.77,
          4.73,
          cabinet,
        )
    }
  }
  for (const y of [0.12, 3.95]) {
    for (const x of [-5.34, 5.34]) b.box('perimeter-moulding', 0.11, 0.09, 9.7, x, y, 0, trim, 0.46)
  }
  b.box('catalog-plinth', 6.8, 0.83, 0.54, 0, 0.445, -3.86, cabinet)
  b.box('catalog-rail', 6.8, 0.38, 0.41, 0, 1.025, -3.78, cabinet, 0.1)
  b.box('catalog-case-ledge', 6.8, 0.065, 0.59, 0, 1.279, -3.72, cabinet, 0.17)
  b.box('catalog-wall-inset', 6.8, 1.88, 0.16, 0, 2.2, -3.96, wall)
  b.box('catalog-header-rail', 6.8, 0.45, 0.34, 0, 3.08, -3.94, cabinet, 0.17)
  b.mesh(
    'catalog-lit-reveal',
    new THREE.BoxGeometry(6.7, 0.03, 0.03),
    b.material(light, 0.05, 0.55, 0.7),
    0,
    2.88,
    -3.77,
  )
  for (const x of [-3.38, 3.38]) b.box('catalog-upright', 0.12, 3.4, 0.42, x, 1.7, -3.83, cabinet)
  b.box('reading-desk', 0.95, 0.11, 2.35, -4.79, 0.87, desk.z, cabinet, 0.02, 0.055)
  for (const z of [-1.83, -0.06]) {
    b.mesh(
      'reading-turned-leg',
      new THREE.CylinderGeometry(0.052, 0.038, 0.81, 18),
      b.material(trim, 0.66),
      -4.66,
      0.41,
      z,
    )
  }
  b.box('reading-screen-housing', 0.09, 1.52, 2.22, desk.x - 0.067, 1.72, desk.z, cabinet, 0.08)
  b.box('reading-screen-stand', 0.1, 0.46, 0.15, desk.x - 0.11, 1.12, desk.z, trim, 0.64)
  b.box('lounge-controls-housing', 0.12, 1.49, 1.0, 4.78, 1.55, -0.8, cabinet, 0.14)
  for (const y of [1.05, 2.03])
    b.box('lounge-control-bracket', 0.66, 0.055, 0.11, 5.05, y, -0.8, trim, 0.56)
  batchOwnedStaticGroup(shell, new Set(['world-floor', 'pressure-porthole', 'observation-rib']))

  const featured = new THREE.Group()
  featured.name = 'room-featured-furniture'
  root.add(featured)
  const f = roomBuilder(featured)
  const blocked: Footprint[] = [
    [0, -3.8, 7, 0.78],
    [-4.79, desk.z, 1.11, 2.43],
  ]
  const occupy = (x: number, z: number, w: number, d: number) => blocked.push([x, z, w, d])
  const finish = f.material(trim, 0.73, 0.39)
  const point = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z)

  if (world === 'afterglow') {
    for (const [x, yaw] of [
      [-2.55, -0.15],
      [-1.25, -0.07],
      [1.35, 0.07],
      [2.65, 0.15],
    ]) {
      createArcadeCabinet(featured, x, yaw, palette)
      occupy(x, 3.77, 1.15, 1.2)
    }
    const carpet = f.material('#3a283b', 0, 0.94)
    f.mesh('arcade-carpet', new THREE.PlaneGeometry(5.7, 5.3), carpet, 0, 0.004, 0.85, -Math.PI / 2)
    // Instanced woven motifs keep the carpet visible at low rendering cost.
    const motifs = new THREE.InstancedMesh(
      new THREE.RingGeometry(0.042, 0.059, 6),
      f.material(trim, 0, 0.92),
      120,
    )
    const stamp = new THREE.Object3D()
    for (let i = 0; i < motifs.count; i++) {
      stamp.position.set(((i % 12) - 5.5) * 0.45, 0.005, (Math.floor(i / 12) - 4.5) * 0.45 + 0.85)
      stamp.rotation.set(-Math.PI / 2, 0, (i % 3) * 0.35)
      stamp.updateMatrix()
      motifs.setMatrixAt(i, stamp.matrix)
    }
    featured.add(motifs)
  } else if (world === 'monochrome') {
    f.box('precision-workbench', 3.9, 0.13, 1.37, 0, 0.89, 3.74, cabinet, 0.13)
    for (const x of [-1.65, 1.65]) {
      f.box('workbench-tool-drawers', 0.46, 0.84, 1.08, x, 0.42, 3.74, wall)
      for (const y of [0.24, 0.43, 0.62])
        f.box('brushed-drawer-pull', 0.23, 0.025, 0.045, x, y, 3.172, trim, 0.8)
      f.strut('drafting-arm', point(x, 0.96, 4.23), point(x, 1.65, 4.06), 0.024, trim)
      f.strut('drafting-arm', point(x, 1.65, 4.06), point(x * 0.8, 1.45, 3.62), 0.021, trim)
      f.mesh(
        'drafting-lamp-shade',
        new THREE.ConeGeometry(0.145, 0.13, 24, 1, true),
        finish,
        x * 0.8,
        1.43,
        3.62,
      )
    }
    for (const x of [-0.72, 0, 0.72])
      f.box('drafting-sample', 0.58, 0.014, 0.85, x, 0.963, 3.65, '#d4cbb7')
    occupy(0, 3.74, 3.95, 1.43)
  } else if (world === 'greenhouse') {
    for (const z of [-2.85, 0.95, 3.12]) {
      f.box('planting-trough', 0.68, 0.36, 1.19, 4.37, 0.51, z, cabinet, 0.06)
      f.box('planting-soil', 0.6, 0.045, 1.1, 4.37, 0.69, z, '#281f17')
      for (const dz of [-0.46, 0.46])
        f.box('planter-foot', 0.55, 0.35, 0.083, 4.37, 0.17, z + dz, trim, 0.45)
      for (let i = 0; i < 7; i++) {
        const base = point(4.37 + Math.sin(i * 2.4) * 0.19, 0.71, z + (i - 3) * 0.145)
        const top = base
          .clone()
          .add(point(Math.sin(i) * 0.12, 0.34 + (i % 4) * 0.14, Math.cos(i) * 0.1))
        f.strut('plant-stem', base, top, 0.008, '#52724a')
        for (let j = 0; j < 3; j++) {
          const p = base.clone().lerp(top, (j + 1) / 3)
          const leaf = f.mesh(
            'veined-conservatory-leaf',
            new THREE.SphereGeometry(0.11, 10, 7),
            f.material(j % 2 ? '#396745' : '#638c53', 0, 0.54),
            p.x,
            p.y,
            p.z,
            j * 0.55,
            i * 2.4,
            j % 2 ? -0.53 : 0.53,
          )
          leaf.scale.set(1.45, 0.13, 0.57)
        }
      }
      occupy(4.37, z, 0.76, 1.28)
    }
    f.box('potting-workbench', 3.5, 0.12, 0.95, 0, 0.87, 3.85, cabinet, 0, 0.04)
    for (const x of [-1.45, 1.45])
      f.box('potting-workbench-leg', 0.1, 0.83, 0.79, x, 0.41, 3.85, cabinet)
    occupy(0, 3.85, 3.5, 0.95)
  } else if (world === 'signal') {
    for (const x of [-1.55, 0, 1.55]) {
      f.box('receiver-rack', 1.34, 1.75, 0.74, x, 0.9, 3.84, cabinet)
      for (const y of [0.59, 0.88, 1.17, 1.46]) {
        f.box('receiver-faceplate', 1.24, 0.22, 0.07, x, y, 3.43, '#242a28', 0.42)
        f.mesh(
          'tuning-dial',
          new THREE.CylinderGeometry(0.062, 0.065, 0.08, 22),
          finish,
          x + 0.39,
          y,
          3.36,
          Math.PI / 2,
        )
        f.mesh(
          'receiver-status-lens',
          new THREE.BoxGeometry(0.28, 0.066, 0.012),
          f.material(light, 0, 0.4, 0.45),
          x - 0.33,
          y,
          3.383,
        )
      }
      occupy(x, 3.84, 1.36, 0.8)
    }
    f.box('oscilloscope', 0.78, 0.46, 0.39, 0, 2.023, 3.79, '#384942', 0.1)
    f.mesh(
      'scope-green-phosphor',
      new THREE.PlaneGeometry(0.54, 0.29),
      f.material('#56a786', 0, 0.35, 0.6),
      0,
      2.023,
      3.589,
      0,
      Math.PI,
    )
    const wire = new THREE.CatmullRomCurve3([
      point(-1.2, 0.93, 3.35),
      point(-0.8, 0.4, 3.18),
      point(-0.39, 1.16, 3.34),
    ])
    f.mesh(
      'receiver-patch-cable',
      new THREE.TubeGeometry(wire, 22, 0.014, 7),
      f.material('#a48653', 0, 0.68),
    )
  } else if (world === 'tape-deck') {
    f.box('walnut-mixing-desk', 3.9, 0.88, 1.03, 0, 0.47, 3.85, cabinet, 0.03, 0.11)
    f.box('mixing-desk-deck', 3.61, 0.06, 0.86, 0, 0.94, 3.82, wall, 0.22)
    for (let i = 0; i < 10; i++) {
      const x = (i - 4.5) * 0.19
      f.box('mixer-fader-track', 0.025, 0.008, 0.35, x, 0.975, 3.65, '#181a1b')
      f.box('mixer-fader-cap', 0.09, 0.035, 0.055, x, 0.998, 3.55 + (i % 4) * 0.05, trim, 0.17)
    }
    f.box('reel-to-reel-face', 1.37, 0.75, 0.34, 0, 1.34, 4.03, cabinet, 0.18)
    for (const x of [-0.39, 0.39]) {
      f.mesh(
        'tape-reel',
        new THREE.TorusGeometry(0.22, 0.027, 8, 36),
        f.material(light, 0.66),
        x,
        1.37,
        3.847,
      )
      f.mesh(
        'reel-hub',
        new THREE.CylinderGeometry(0.073, 0.073, 0.04, 20),
        finish,
        x,
        1.37,
        3.847,
        Math.PI / 2,
      )
      for (let i = 0; i < 3; i++) {
        const angle = (i * Math.PI * 2) / 3
        f.strut(
          'reel-spoke',
          point(x, 1.37, 3.847),
          point(x + Math.sin(angle) * 0.2, 1.37 + Math.cos(angle) * 0.2, 3.847),
          0.015,
          light,
        )
      }
    }
    occupy(0, 3.85, 3.9, 1.08)
  } else {
    const orbital = world === 'deep-space'
    const tableZ = 3.58
    f.mesh(
      orbital ? 'projection-table-base' : 'sonar-chart-base',
      new THREE.CylinderGeometry(0.67, 0.85, 0.77, orbital ? 8 : 40),
      f.material(cabinet, 0.26),
      0,
      0.39,
      tableZ,
    )
    f.mesh(
      orbital ? 'projection-table' : 'sonar-chart-table',
      new THREE.CylinderGeometry(1.34, 1.17, 0.16, orbital ? 8 : 48),
      finish,
      0,
      0.87,
      tableZ,
    )
    f.mesh(
      'recessed-instrument-deck',
      new THREE.CircleGeometry(1.15, orbital ? 8 : 48),
      f.material(wall, 0.4, 0.38),
      0,
      0.955,
      tableZ,
      -Math.PI / 2,
    )
    for (const radius of [0.3, 0.57, 0.87, 1.08]) {
      f.mesh(
        'chart-range-ring',
        new THREE.TorusGeometry(radius, 0.007, 5, 65),
        f.material(light, 0.2, 0.46, 0.22),
        0,
        0.962,
        tableZ,
        Math.PI / 2,
      )
    }
    occupy(0, tableZ, 2.69, 2.69)
  }
  for (const z of [1.6, 2.98]) {
    const seat = new THREE.Group()
    seat.position.set(3.6, 0, z)
    seat.rotation.y = -Math.PI / 2 + 0.28
    featured.add(seat)
    const s = roomBuilder(seat)
    s.box('lounge-seat-plinth', 1.12, 0.16, 0.96, 0, 0.23, 0, cabinet)
    s.mesh(
      'lounge-seat-cushion',
      upholsteredPanel(1.08, 0.28, 0.89),
      s.material(upholstery, 0, 0.87),
      0,
      0.44,
      0,
    )
    s.mesh(
      'lounge-seat-back',
      upholsteredPanel(1.1, 0.69, 0.21, true),
      s.material(upholstery, 0, 0.87),
      0,
      0.78,
      0.39,
    )
    for (const x of [-0.48, 0.48])
      s.box('lounge-arm-cap', 0.16, 0.1, 0.88, x, 0.65, 0, cabinet, 0.12)
    occupy(3.6, z, 1.16, 1.24)
  }

  const ambient = new THREE.HemisphereLight(light, '#5c4a40', 0.85)
  const key = new THREE.DirectionalLight('#f0dec8', 1.7)
  key.position.set(-2, 4.1, 1.6)
  key.castShadow = true
  key.shadow.mapSize.set(1024, 1024)
  Object.assign(key.shadow.camera, { left: -6, right: 6, bottom: -5, top: 5, far: 18 })
  key.shadow.normalBias = 0.028
  root.add(ambient, key)
  for (const [x, z, color] of [
    [-2.5, -2, light],
    [2.5, 2.3, world === 'afterglow' ? '#f28aa9' : light],
  ] as const) {
    const lamp = new THREE.PointLight(color, 8, 6)
    lamp.position.set(x, 3.23, z)
    root.add(lamp)
    f.mesh(
      'fixture-shade',
      new THREE.ConeGeometry(0.27, 0.19, 28, 1, true),
      f.material(cabinet, 0.31, 0.52),
      x,
      3.42,
      z,
    )
    f.mesh(
      'frosted-fixture-diffuser',
      new THREE.SphereGeometry(0.072, 18, 10),
      f.material(color, 0, 0.57, 0.8),
      x,
      3.26,
      z,
    )
    f.strut('fixture-hanger', point(x, 3.47, z), point(x, 4.52, z), 0.012, trim)
  }
  return {
    group: root,
    canStandAt(x: number, z: number) {
      return (
        Number.isFinite(x) &&
        Number.isFinite(z) &&
        Math.abs(x) <= 4.65 &&
        z >= -3.28 &&
        z <= 4.5 &&
        !blocked.some(
          ([cx, cz, width, depth]) =>
            Math.abs(x - cx) < width / 2 + 0.11 && Math.abs(z - cz) < depth / 2 + 0.11,
        )
      )
    },
    dispose: () => disposeRoomGroup(root),
  }
}
