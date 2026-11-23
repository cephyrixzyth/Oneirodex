import * as THREE from 'three'
import {
  disposeRoomGroup,
  roomBuilder,
  beveledBox,
  upholsteredPanel,
  batchOwnedStaticGroup,
} from './roomGeometry'
import { createRoomMaterialLibrary } from './roomMaterials'
import { addObservatoryJoinery } from './roomJoinery'
import { OBSERVATORY_SURFACES, ORRERY_POSITION as O, TELESCOPE_POSITION as T } from './roomLayout'
import { detailTelescope, detailOrrery } from './roomInstruments'

const brass = '#c9a96b',
  wood = '#69442e',
  velvet = '#164938'

/** First authored world. The shader sky and geometry are original project assets. */
export function furnishObservatory(
  scene: THREE.Scene,
  sharedMaterials?: ReturnType<typeof createRoomMaterialLibrary>,
) {
  const root = new THREE.Group()
  root.name = 'aurora-observatory'
  scene.add(root)
  const materials = sharedMaterials || createRoomMaterialLibrary()
  const b = roomBuilder(root, materials.material)
  addObservatoryJoinery(root, materials)
  const sky = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: { time: { value: 0 } },
    vertexShader:
      'varying vec2 skyUV; void main(){skyUV=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
    fragmentShader: `
      varying vec2 skyUV; uniform float time;
      float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1.,0.)),f.x),mix(hash(i+vec2(0.,1.)),hash(i+vec2(1.)),f.x),f.y);}
      void main(){
        vec2 uv=skyUV;
        vec3 color=mix(vec3(.0015,.004,.012),vec3(.008,.019,.032),exp(-abs(uv.y-.5)*9.));
        vec2 cells=uv*vec2(1100.,480.);
        float stars=step(.997,hash(floor(cells)))*pow(max(0.,1.-length(fract(cells)-.5)*2.),7.);
        color+=vec3(.55,.64,.7)*stars*smoothstep(.49,.60,uv.y);
        for(int i=0;i<2;i++){
          float f=float(i),fold=noise(vec2(uv.x*24.+f*7.,time*.008));
          float base=.60+.028*sin(uv.x*10.+f*2.+time*.006)+.014*fold+f*.027;
          float height=uv.y-base;
          float rays=pow(.5+.5*sin(uv.x*420.+fold*19.+time*.015),3.);
          float lower=exp(-abs(height)*175.);
          float curtain=smoothstep(-.003,.008,height)*exp(-max(0.,height)*39.)*(.1+rays*.9);
          vec3 green=mix(vec3(.035,.24,.10),vec3(.055,.10,.18),smoothstep(.015,.07,height));
          color+=green*(lower*.45+curtain*.7)*(.65+.35*fold);
        }
        vec2 moon=(uv-vec2(.68,.68))*vec2(2.,1.);
        float disk=1.-smoothstep(.00145,.00155,length(moon));
        float cut=smoothstep(.0014,.0015,length(moon-vec2(.0008,.0002)));
        color+=vec3(.85,.83,.62)*disk*cut;
        gl_FragColor=vec4(color,1.);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  })
  const skyMesh = b.mesh('observatory-aurora', new THREE.SphereGeometry(18, 40, 24), sky, 0, 0, 0)
  skyMesh.castShadow = false
  skyMesh.renderOrder = -1000
  for (let layer = 0; layer < 3; layer++) {
    const vertices: number[] = [],
      segments = 96,
      radius = 16 + layer * 4
    for (let i = 0; i < segments; i++) {
      const a = (i / segments) * Math.PI * 2,
        b = ((i + 1) / segments) * Math.PI * 2
      const height = (angle: number) =>
        0.3 +
        layer * 0.25 +
        Math.sin(angle * 5 + layer) * 0.6 +
        Math.sin(angle * 11 + layer * 3) * 0.24
      const ax = Math.cos(a) * radius,
        az = Math.sin(a) * radius,
        bx = Math.cos(b) * radius,
        bz = Math.sin(b) * radius
      vertices.push(
        ax,
        -2,
        az,
        bx,
        -2,
        bz,
        bx,
        height(b),
        bz,
        ax,
        -2,
        az,
        bx,
        height(b),
        bz,
        ax,
        height(a),
        az,
      )
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
    const ridge = b.mesh(
      'distant-mountain-ridge',
      geometry,
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(['#07131c', '#0a1822', '#0d1c27'][layer]),
        side: THREE.DoubleSide,
      }),
    )
    ridge.castShadow = false
    ridge.receiveShadow = false
  }
  skyMesh.receiveShadow = false
  skyMesh.renderOrder = -10
  b.mesh(
    'observatory-floor',
    new THREE.CylinderGeometry(5.65, 5.65, 0.12, 64),
    materials.surface('floor'),
    0,
    -0.08,
    0,
  )
  const object = new THREE.Object3D()
  const floor = new THREE.Mesh(new THREE.CircleGeometry(5.55, 96), materials.surface('floor'))
  floor.name = 'observatory-walnut-boards'
  floor.rotation.x = -Math.PI / 2
  floor.position.y = OBSERVATORY_SURFACES.floor
  floor.receiveShadow = true
  root.add(floor)
  const carpet = b.mesh(
    'observatory-rug',
    new THREE.CircleGeometry(3.25, 64),
    materials.surface('velvet'),
    0,
    OBSERVATORY_SURFACES.rug,
    0,
    -Math.PI / 2,
  )
  carpet.receiveShadow = true
  for (const radius of [3.08, 3.16])
    b.mesh(
      'rug-stitched-border',
      new THREE.TorusGeometry(radius, 0.014, 6, 64),
      b.material('#a58c5a'),
      0,
      0.023,
      0,
      Math.PI / 2,
    )
  const glass = new THREE.MeshPhysicalMaterial({
    color: new THREE.Color('#24473c'),
    roughness: 0.22,
    metalness: 0.12,
    transparent: true,
    opacity: 0.16,
    side: THREE.DoubleSide,
    depthWrite: false,
  })
  const dome = b.mesh(
    'observatory-dome',
    new THREE.SphereGeometry(5.6, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2),
    glass,
    0,
    3.35,
    0,
  )
  dome.scale.y = 0.43
  dome.castShadow = false
  for (let i = 0; i < 6; i++) {
    const arch = b.mesh(
      'dome-rib-' + i,
      new THREE.TorusGeometry(5.6, 0.045, 8, 64, Math.PI),
      b.material(brass, 0.65, 0.34),
      0,
      3.35,
      0,
      0,
      (i * Math.PI) / 6,
    )
    arch.scale.y = 0.43
  }
  b.mesh(
    'dome-cornice',
    new THREE.TorusGeometry(5.6, 0.085, 8, 80),
    b.material(wood),
    0,
    3.35,
    0,
    Math.PI / 2,
  )
  // Substantial window framing: the moving sky is outside it, not pasted on a lounge panel.
  b.box('window-sill', 0.22, 0.15, 6.4, 5.15, 0.8, 0, wood)
  b.box('window-header', 0.22, 0.16, 6.4, 5.15, 3.48, 0, wood)
  for (const z of [-3.15, -1.58, 0, 1.58, 3.15])
    b.box('window-mullion', 0.13, 2.7, 0.075, 5.15, 2.15, z, brass, 0.6)
  const library = new THREE.Group()
  library.name = 'observatory-library'
  root.add(library)
  const lb = roomBuilder(library, materials.material)
  lb.box('library-back-panel', 6.7, 3.55, 0.2, 0, 1.8, -4.03, '#163128')
  for (const x of [-3.2, 3.2]) lb.box('library-fluted-pier', 0.16, 3.6, 0.5, x, 1.8, -3.85, wood)
  for (const side of [-1, 1]) {
    const wing = new THREE.Group()
    wing.name = 'curved-library-bay'
    wing.position.set(side * 3.65, 0, -3.05)
    wing.rotation.y = -side * 0.4
    library.add(wing)
    const wb = roomBuilder(wing, materials.material)
    wb.box('bookcase-rear', 1.52, 3.5, 0.12, 0, 1.8, -0.18, wood)
    for (const x of [-0.73, 0.73]) wb.box('bookcase-pier', 0.12, 3.6, 0.5, x, 1.8, 0, wood)
    for (const y of [0.62, 1.32, 2.08, 2.82, 3.58])
      wb.box('bookcase-shelf', 1.4, 0.09, 0.47, 0, y, 0.05, wood)
    wb.box('bookcase-crown', 1.64, 0.13, 0.58, 0, 3.65, 0, wood)
    batchOwnedStaticGroup(wing)
  }
  lb.box('collection-display-plinth', 6.3, 0.2, 0.65, 0, 0.78, -3.73, wood)
  lb.box('collection-cabinet-base', 6.3, 0.64, 0.65, 0, 0.34, -3.73, wood, 0, 0.035)
  lb.box('collection-case-display-ledge', 6.4, 0.07, 0.58, 0, 1.2775, -3.7, wood, 0, 0.025)
  lb.box('collection-label-mounting-rail', 6.3, 0.3, 0.48, 0, 1.02, -3.75, wood, 0, 0.02)
  lb.box('collection-header-mounting-rail', 6.7, 0.55, 0.25, 0, 3.08, -3.92, wood, 0, 0.025)
  for (const x of [-2.5, -1.25, 0, 1.25, 2.5])
    b.strut(
      'collection-ledge-bracket',
      new THREE.Vector3(x, 0.91, -3.93),
      new THREE.Vector3(x, 1.24, -3.48),
      0.022,
      brass,
    )
  lb.box('collection-display-cornice', 6.3, 0.15, 0.48, 0, 2.78, -3.78, wood)
  const bindings = ['#2c5543', '#704e3a', '#5a3e56', '#9c8555', '#314b5e', '#596149']
  const spineBands: THREE.Matrix4[] = []
  for (let color = 0; color < bindings.length; color++) {
    const matrices: THREE.Matrix4[] = []
    for (const side of [-1, 1])
      for (let shelf = 0; shelf < 4; shelf++)
        for (let i = 0; i < 9; i++) {
          if ((i + shelf) % bindings.length !== color) continue
          const height = 0.35 + (i % 4) * 0.045
          const angle = -side * 0.4,
            localX = -0.57 + i * 0.14
          object.position.set(
            side * 3.65 + Math.cos(angle) * localX + Math.sin(angle) * 0.05,
            0.68 + shelf * 0.74 + height / 2,
            -3.05 - Math.sin(angle) * localX + Math.cos(angle) * 0.05,
          )
          object.rotation.set(0, angle, i % 5 === 0 ? 0.07 : 0)
          object.scale.set(0.115, height, 0.25)
          object.updateMatrix()
          matrices.push(object.matrix.clone())
          for (const y of [-0.3, 0.3])
            spineBands.push(
              object.matrix
                .clone()
                .multiply(new THREE.Matrix4().makeTranslation(0, y, 0.51))
                .multiply(new THREE.Matrix4().makeScale(0.92, 0.024, 0.02)),
            )
        }
    const books = new THREE.InstancedMesh(
      beveledBox(1, 1, 1, 0.02),
      materials.own(
        new THREE.MeshStandardMaterial({
          color: new THREE.Color(bindings[color]),
          roughness: 0.85,
          normalMap: materials.surface('velvet').normalMap,
          roughnessMap: materials.surface('velvet').roughnessMap,
        }),
      ),
      matrices.length,
    )
    books.name = 'library-bindings-' + color
    matrices.forEach((matrix, i) => books.setMatrixAt(i, matrix))
    books.castShadow = true
    books.receiveShadow = true
    library.add(books)
  }
  const gilt = new THREE.InstancedMesh(
    new THREE.BoxGeometry(1, 1, 1),
    materials.material(brass, 0.8, 0.4, 0),
    spineBands.length,
  )
  gilt.name = 'book-spine-gilding'
  spineBands.forEach((matrix, index) => gilt.setMatrixAt(index, matrix))
  gilt.receiveShadow = true
  library.add(gilt)
  const seating = new THREE.Group()
  seating.name = 'observatory-seating'
  root.add(seating)
  const sb = roomBuilder(seating, materials.material)
  for (const side of [-1, 1]) {
    const x = side * 3.15,
      z = 2.8
    sb.box('walnut-chair-base', 1.3, 0.18, 1.15, x, 0.28, z, wood)
    sb.mesh(
      'velvet-chair-seat',
      upholsteredPanel(1.19, 0.3, 1.01),
      materials.surface('velvet'),
      x,
      0.48,
      z,
    )
    sb.mesh(
      'velvet-chair-back',
      upholsteredPanel(1.25, 0.8, 0.24, true),
      materials.surface('velvet'),
      x,
      0.92,
      z + 0.46,
    ).rotation.x = -0.12
    for (const arm of [-0.62, 0.62])
      sb.box('curved-chair-arm', 0.17, 0.32, 1.13, x + arm, 0.72, z, velvet, 0, 0.06)
    for (const dx of [-0.48, 0.48])
      for (const dz of [-0.4, 0.4])
        sb.box('brass-chair-foot', 0.07, 0.2, 0.07, x + dx, 0.1, z + dz, brass, 0.7)
  }
  b.box('reading-desk', 1.05, 0.13, 2.3, -4.53, 0.84, -0.95, wood)
  for (const z of [-1.8, -0.1])
    b.box('reading-desk-leg', 0.13, 0.8, 0.13, -4.53, 0.4, z, brass, 0.6)
  const telescope = new THREE.Group()
  telescope.name = 'observatory-telescope'
  root.add(telescope)
  const tb = roomBuilder(telescope, materials.material)
  telescope.position.set(T.x, 0, T.z)
  telescope.rotation.y = -0.4
  tb.mesh(
    'telescope-tube',
    new THREE.CylinderGeometry(0.12, 0.16, 1.05, 24),
    tb.material('#17352e', 0.2, 0.42),
    0,
    1.5,
    0,
    0.8,
  )
  tb.mesh(
    'telescope-lens',
    new THREE.CylinderGeometry(0.105, 0.105, 0.025, 24),
    tb.material('#2d8291', 0.8, 0.12),
    0,
    1.87,
    0.38,
    0.8,
  )
  for (let i = 0; i < 3; i++)
    tb.strut(
      'telescope-tripod',
      new THREE.Vector3(0, 1.23, 0),
      new THREE.Vector3(
        Math.sin((i * Math.PI * 2) / 3) * 0.5,
        0.04,
        Math.cos((i * Math.PI * 2) / 3) * 0.5,
      ),
      0.034,
      brass,
    )
  const orrery = new THREE.Group()
  orrery.name = 'observatory-orrery'
  root.add(orrery)
  orrery.position.set(O.x, 1.08, O.z)
  b.mesh(
    'orrery-pedestal',
    new THREE.CylinderGeometry(0.44, 0.33, 0.12, 32),
    b.material(wood),
    O.x,
    0.96,
    O.z,
  )
  b.mesh(
    'orrery-column',
    new THREE.CylinderGeometry(0.09, 0.14, 0.88, 16),
    b.material(brass, 0.7),
    O.x,
    0.44,
    O.z,
  )
  const ob = roomBuilder(orrery, materials.material)
  for (let i = 0; i < 3; i++) {
    const radius = 0.2 + i * 0.115
    ob.mesh(
      'orrery-orbit-' + i,
      new THREE.TorusGeometry(radius, 0.012, 6, 40),
      ob.material(brass, 0.8),
      0,
      i * 0.035,
      0,
      Math.PI / 2,
      0,
      i * 0.25,
    )
    ob.mesh(
      'orrery-planet-' + i,
      new THREE.SphereGeometry(0.035 + i * 0.012, 12, 8),
      ob.material(['#c9a96b', '#8dbba6', '#8c9ec6'][i], 0.3),
      radius,
      i * 0.035,
      0,
    )
  }
  ob.mesh(
    'orrery-sun',
    new THREE.SphereGeometry(0.075, 16, 12),
    ob.material('#ffdda0', 0.2, 0.4, 0.3),
  )
  const ambient = new THREE.HemisphereLight('#b8d9eb', '#533923', 0.35)
  root.add(ambient)
  const moon = new THREE.DirectionalLight('#b9d5ed', 1.5)
  moon.position.set(4.8, 6, 1)
  moon.castShadow = true
  moon.shadow.mapSize.set(1024, 1024)
  Object.assign(moon.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6, near: 0.5, far: 20 })
  moon.shadow.normalBias = 0.035
  root.add(moon)
  const collectionLight = new THREE.PointLight('#f5d7a0', 4.5, 6, 2)
  collectionLight.position.set(0, 2.8, -2.7)
  root.add(collectionLight)
  for (const x of [-3, 3]) {
    b.strut(
      'pendant-cable',
      new THREE.Vector3(x, 4.9, 0),
      new THREE.Vector3(x, 3.3, 0),
      0.014,
      '#45392d',
    )
    b.mesh(
      'pendant-shade',
      new THREE.ConeGeometry(0.35, 0.3, 24, 1, true),
      b.material(brass, 0.65),
      x,
      3.25,
      0,
    )
    b.mesh(
      'pendant-lamp',
      new THREE.SphereGeometry(0.08, 12, 8),
      b.material('#ffdc9b', 0, 0.4, 0.8),
      x,
      3.13,
      0,
    )
    const lamp = new THREE.PointLight('#ffcf8d', 6.5, 6, 2)
    lamp.position.set(x, 3.05, 0)
    root.add(lamp)
  }
  let disposed = false
  let orreryOffset = 0
  const head = new THREE.Group()
  head.name = 'telescope-head'
  head.position.y = 1.23
  telescope.add(head)
  detailTelescope(head, materials)
  detailOrrery(orrery, materials)
  const actionMeshes: THREE.Mesh[] = []
  for (const name of ['telescope-tube', 'telescope-lens']) {
    const mesh = telescope.getObjectByName(name) as THREE.Mesh
    head.attach(mesh)
    mesh.userData.action = '@instrument-telescope'
    actionMeshes.push(mesh)
  }
  const sun = orrery.getObjectByName('orrery-sun') as THREE.Mesh
  sun.userData.action = '@instrument-orrery'
  actionMeshes.push(sun)
  let lastSeconds = 0,
    lastReduced = false
  function instruments() {
    orrery.rotation.y = orreryOffset + (lastReduced ? 0 : lastSeconds * 0.06)
  }
  return {
    group: root,
    actionMeshes,
    interact(kind: 'telescope' | 'orrery') {
      if (disposed) return
      if (kind === 'telescope') head.rotation.y = (head.rotation.y + Math.PI / 6) % (Math.PI * 2)
      else {
        orreryOffset += Math.PI / 6
        instruments()
      }
    },
    update(seconds: number, reducedMotion = false) {
      if (disposed || !Number.isFinite(seconds)) return
      sky.uniforms.time.value = reducedMotion ? 0 : seconds % 100_000
      lastSeconds = seconds
      lastReduced = reducedMotion
      instruments()
    },
    canStandAt(x: number, z: number, consoleVisible = false) {
      if (!Number.isFinite(x) || !Number.isFinite(z) || Math.hypot(x, z) > 5.2) return false
      if (Math.abs(x) < 1.04 && z > -1.8 && z < 1.98) return false
      if (consoleVisible && Math.abs(x - 1.25) < 0.58 && Math.abs(z - 0.35) < 0.48) return false
      if (z < -3.3 && Math.abs(x) < 3.4) return false
      if (x > 4.4 && z > -1.45 && z < -0.15) return false
      if (Math.abs(Math.abs(x) - 3.15) < 0.86 && Math.abs(z - 2.8) < 0.85) return false
      if (Math.hypot(x - T.x, z - T.z) < 0.8 || Math.hypot(x - O.x, z - O.z) < 0.68) return false
      if (Math.abs(Math.abs(x) - 3.65) < 0.95 && Math.abs(z + 3.05) < 0.65) return false
      return !(x < -3.8 && z > -2.25 && z < 0.45)
    },
    setQuality(quality: 'low' | 'standard' | 'high') {
      moon.castShadow = quality !== 'low'
      const size = quality === 'high' ? 2048 : 1024
      if (moon.shadow.mapSize.x !== size) {
        moon.shadow.map?.dispose()
        moon.shadow.map = null
        moon.shadow.mapSize.set(size, size)
      }
    },
    dispose() {
      if (!disposed) {
        disposed = true
        disposeRoomGroup(root, materials.owned)
        if (!sharedMaterials) materials.dispose()
      }
    },
  }
}
