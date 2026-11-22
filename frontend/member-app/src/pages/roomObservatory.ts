import * as THREE from 'three'
import { disposeRoomGroup, roomBuilder, beveledBox } from './roomGeometry'

const brass = '#c9a96b',
  wood = '#69442e',
  darkWood = '#38271f',
  velvet = '#164938'

/** First authored world. The shader sky and geometry are original project assets. */
export function furnishObservatory(scene: THREE.Scene) {
  const root = new THREE.Group()
  root.name = 'aurora-observatory'
  scene.add(root)
  const b = roomBuilder(root)
  const sky = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: { time: { value: 0 } },
    vertexShader:
      'varying vec2 skyUV; void main(){skyUV=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
    fragmentShader: `
      varying vec2 skyUV; uniform float time;
      float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      void main(){
        vec2 uv=skyUV;
        vec3 color=mix(vec3(.003,.012,.025),vec3(.015,.045,.075),smoothstep(.4,.85,uv.y));
        vec2 cells=uv*vec2(550.,240.);
        float stars=step(.994,hash(floor(cells)))*pow(max(0.,1.-length(fract(cells)-.5)*2.),7.);
        color+=vec3(.55,.7,.8)*stars*smoothstep(.4,.65,uv.y);
        for(int i=0;i<3;i++){
          float f=float(i);float wave=.60+.065*sin(uv.x*13.+time*.035+f)+.025*sin(uv.x*29.-time*.022);
          float glow=exp(-abs(uv.y-wave-f*.018)*95.);
          float curtain=.5+.5*sin(uv.x*97.+time*.05+f*2.);
          color+=mix(vec3(.06,.4,.25),vec3(.2,.48,.65),f/3.)*glow*(.4+curtain*.6);
        }
        vec2 moon=(uv-vec2(.68,.68))*vec2(2.2,1.);
        float disk=1.-smoothstep(.015,.016,length(moon));
        float cut=smoothstep(.014,.015,length(moon-vec2(.009,.003)));
        color+=vec3(.85,.83,.62)*disk*cut;
        gl_FragColor=vec4(color,1.);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  })
  const skyMesh = b.mesh('observatory-aurora', new THREE.SphereGeometry(18, 40, 24), sky, 0, 0, 0)
  skyMesh.castShadow = false
  skyMesh.receiveShadow = false
  skyMesh.renderOrder = -10
  b.mesh(
    'observatory-floor',
    new THREE.CylinderGeometry(5.65, 5.65, 0.12, 64),
    b.material(darkWood),
    0,
    -0.08,
    0,
  )
  const boards: THREE.Matrix4[] = [],
    object = new THREE.Object3D()
  for (let i = -10; i <= 10; i++) {
    const x = i * 0.5,
      half = Math.sqrt(Math.max(0, 5.5 ** 2 - (Math.abs(x) + 0.25) ** 2))
    const count = Math.max(1, Math.ceil((half * 2) / 1.8)),
      length = (half * 2) / count
    for (let j = 0; j < count; j++) {
      object.position.set(x, -0.005, -half + length * (j + 0.5))
      object.scale.set(0.49, 0.025, Math.max(0.02, length - 0.012))
      object.updateMatrix()
      boards.push(object.matrix.clone())
    }
  }
  const floor = new THREE.InstancedMesh(
    beveledBox(1, 1, 1, 0.01),
    b.material('#765039'),
    boards.length,
  )
  floor.name = 'observatory-walnut-boards'
  boards.forEach((matrix, i) => {
    floor.setMatrixAt(i, matrix)
    floor.setColorAt(i, new THREE.Color(i % 3 ? '#d1bda3' : '#e4caa3'))
  })
  floor.receiveShadow = true
  root.add(floor)
  const carpet = b.mesh(
    'observatory-rug',
    new THREE.CircleGeometry(3.25, 64),
    b.material('#15352c', 0, 0.98),
    0,
    0.018,
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
  const lb = roomBuilder(library)
  lb.box('library-back-panel', 9.5, 3.55, 0.2, 0, 1.8, -4.03, '#163128')
  for (const x of [-4.65, -3.2, 3.2, 4.65])
    lb.box('library-fluted-pier', 0.16, 3.6, 0.5, x, 1.8, -3.85, wood)
  for (const y of [0.62, 1.32, 2.08, 2.82, 3.58]) {
    lb.box('left-book-shelf', 1.4, 0.09, 0.47, -3.94, y, -3.72, wood)
    lb.box('right-book-shelf', 1.4, 0.09, 0.47, 3.94, y, -3.72, wood)
  }
  lb.box('collection-display-plinth', 6.3, 0.2, 0.65, 0, 0.78, -3.73, wood)
  lb.box('collection-display-cornice', 6.3, 0.15, 0.48, 0, 2.78, -3.78, wood)
  const bindings = ['#2c5543', '#704e3a', '#5a3e56', '#9c8555', '#314b5e', '#596149']
  for (let color = 0; color < bindings.length; color++) {
    const matrices: THREE.Matrix4[] = []
    for (const side of [-1, 1])
      for (let shelf = 0; shelf < 4; shelf++)
        for (let i = 0; i < 9; i++) {
          if ((i + shelf) % bindings.length !== color) continue
          const height = 0.35 + (i % 4) * 0.045
          object.position.set(
            side * 3.94 - 0.57 + i * 0.14,
            0.68 + shelf * 0.74 + height / 2,
            -3.68,
          )
          object.rotation.set(0, 0, i % 5 === 0 ? 0.07 : 0)
          object.scale.set(0.115, height, 0.25)
          object.updateMatrix()
          matrices.push(object.matrix.clone())
        }
    const books = new THREE.InstancedMesh(
      beveledBox(1, 1, 1, 0.02),
      lb.material(bindings[color], 0, 0.78),
      matrices.length,
    )
    books.name = 'library-bindings-' + color
    matrices.forEach((matrix, i) => books.setMatrixAt(i, matrix))
    books.castShadow = true
    books.receiveShadow = true
    library.add(books)
  }
  const seating = new THREE.Group()
  seating.name = 'observatory-seating'
  root.add(seating)
  const sb = roomBuilder(seating)
  for (const side of [-1, 1]) {
    const x = side * 3.15,
      z = 2.8
    sb.box('walnut-chair-base', 1.3, 0.18, 1.15, x, 0.28, z, wood)
    sb.box('velvet-chair-seat', 1.19, 0.3, 1.01, x, 0.48, z, velvet, 0, 0.1)
    sb.box('velvet-chair-back', 1.25, 0.8, 0.24, x, 0.92, z + 0.46, velvet, 0, 0.075).rotation.x =
      -0.12
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
  const tb = roomBuilder(telescope)
  telescope.position.set(3.7, 0, -2.4)
  telescope.rotation.y = -0.4
  tb.mesh(
    'telescope-tube',
    new THREE.CylinderGeometry(0.12, 0.16, 1.05, 24),
    tb.material(brass, 0.75, 0.3),
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
  orrery.position.set(-3.5, 1.08, 2.1)
  b.mesh(
    'orrery-pedestal',
    new THREE.CylinderGeometry(0.44, 0.33, 0.12, 32),
    b.material(wood),
    -3.5,
    0.96,
    2.1,
  )
  b.mesh(
    'orrery-column',
    new THREE.CylinderGeometry(0.09, 0.14, 0.88, 16),
    b.material(brass, 0.7),
    -3.5,
    0.44,
    2.1,
  )
  const ob = roomBuilder(orrery)
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
  const ambient = new THREE.HemisphereLight('#b8d9eb', '#533923', 1.1)
  root.add(ambient)
  const moon = new THREE.DirectionalLight('#b9d5ed', 2.6)
  moon.position.set(4.8, 6, 1)
  moon.castShadow = true
  moon.shadow.mapSize.set(1024, 1024)
  Object.assign(moon.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6, near: 0.5, far: 20 })
  moon.shadow.normalBias = 0.035
  root.add(moon)
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
    const lamp = new THREE.PointLight('#ffcf8d', 8, 6, 2)
    lamp.position.set(x, 3.05, 0)
    root.add(lamp)
  }
  let disposed = false
  let orreryOffset = 0
  const head = new THREE.Group()
  head.name = 'telescope-head'
  head.position.y = 1.23
  telescope.add(head)
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
    canStandAt(x: number, z: number) {
      if (!Number.isFinite(x) || !Number.isFinite(z) || Math.hypot(x, z) > 5.2) return false
      if (Math.abs(x) < 1.04 && z > -1.8 && z < 1.98) return false
      if (Math.abs(Math.abs(x) - 3.15) < 0.86 && Math.abs(z - 2.8) < 0.85) return false
      if (Math.hypot(x - 3.7, z + 2.4) < 0.8 || Math.hypot(x + 3.5, z - 2.1) < 0.68) return false
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
        disposeRoomGroup(root)
      }
    },
  }
}
