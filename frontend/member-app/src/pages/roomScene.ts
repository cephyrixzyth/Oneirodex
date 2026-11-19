import * as THREE from 'three'
import { readingTexture } from './roomReading'
import { furnishRoom, roomFinish, roomArtSlug } from './roomFurnishings'

export interface RoomGame {
  is_favorite?: boolean
  uuid: string
  name: string
  cover_url?: string | null
  summary?: string | null
  size?: string | null
  vr_compat?: string | null
}
export interface RoomView {
  largeText?: boolean
  comfort?: 'Standard' | 'Seated' | 'Close reach'
  favoriteMessage: string
  collection: boolean
  games: RoomGame[]
  selected: RoomGame | null
  detailMessage: string
  shelf: string
  previous: boolean
  next: boolean
}
export type RoomAction = (id: string) => void
export type Station = 'library' | 'reading' | 'lounge'

function labelTexture(title: string, subtitle: string, accent: string, ratio: number) {
  const canvas = document.createElement('canvas')
  canvas.width = 800
  canvas.height = Math.round(canvas.width / ratio)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Room lettering requires a canvas.')
  ctx.fillStyle = '#152124'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = accent
  ctx.fillRect(0, 0, 8, canvas.height)
  const inset = 30
  const titleSize = Math.min(94, Math.round(canvas.height * 0.27))
  const bodySize = Math.min(56, Math.round(titleSize * 0.68))
  let y = titleSize + 8
  function lines(text: string, font: string, height: number, limit: number, color: string) {
    ctx!.font = font
    ctx!.fillStyle = color
    const words = text.trim().split(/\s+/)
    for (let i = 0; i < limit && words.length; i++) {
      let line = words.shift() || ''
      while (
        words.length &&
        ctx!.measureText(line + ' ' + words[0]).width < canvas.width - inset * 2
      )
        line += ' ' + words.shift()
      if (i === limit - 1 && words.length) line += '…'
      ctx!.fillText(line, inset, y, canvas.width - inset * 2)
      y += height
    }
  }
  lines(title, `bold ${titleSize}px sans-serif`, titleSize * 1.12, ratio > 3 ? 1 : 2, '#f5f5eb')
  y += 10
  lines(
    subtitle,
    `${bodySize}px sans-serif`,
    bodySize * 1.17,
    Math.max(1, Math.floor((canvas.height - y + bodySize) / (bodySize * 1.17))),
    '#c5d4cb',
  )
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

export function createRoom(
  canvas: HTMLCanvasElement,
  select: RoomAction,
  changeSession: (active: boolean) => void,
  report: (message: string) => void,
) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    powerPreference: 'low-power',
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6))
  renderer.xr.enabled = true
  renderer.xr.setReferenceSpaceType('local-floor')
  const scene = new THREE.Scene()
  const style = getComputedStyle(document.documentElement)
  const accent = style.getPropertyValue('--od-accent').trim() || '#82c9ae'
  scene.background = new THREE.Color('#101b20')
  const camera = new THREE.PerspectiveCamera(55, 1, 0.05, 45)
  camera.rotation.order = 'YXZ'
  const rig = new THREE.Group()
  rig.add(camera)
  scene.add(rig)
  const theme = document.documentElement.dataset.theme || 'greenhouse'
  const finish = roomFinish(theme)
  furnishRoom(scene, theme)
  const gallery = new THREE.Group()
  scene.add(gallery)
  const targets: THREE.Mesh[] = []
  const ray = new THREE.Raycaster()
  let disposed = false
  let revision = 0
  let activeSession: XRSession | null = null
  let currentView: RoomView | undefined
  let readingPage = 0
  let readingPageCount = 1
  let station: Station = 'library'
  let yaw = 0
  const render = () => {
    if (!disposed && !renderer.xr.isPresenting) renderer.render(scene, camera)
  }
  const resize = () => {
    if (disposed || renderer.xr.isPresenting) return
    const { width, height } = canvas.getBoundingClientRect()
    if (!width || !height) return
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    render()
  }
  const positions: Record<Station, [number, number, number]> = {
    library: [0, 0, 2.1],
    reading: [-2.65, 0, -0.95],
    lounge: [2.65, 0, -0.95],
  }
  function move(next: Station) {
    station = next
    yaw = 0
    rig.position.set(...positions[next])
    const mode = currentView?.comfort
    if (mode === 'Seated') rig.position.y += 0.38
    if (mode === 'Close reach') {
      if (next === 'library') rig.position.z -= 0.8
      else rig.position.x += next === 'reading' ? -0.65 : 0.65
    }
    rig.rotation.y = next === 'reading' ? Math.PI / 2 : next === 'lounge' ? -Math.PI / 2 : 0
    camera.position.set(0, 1.55, 0)
    camera.rotation.set(0, 0, 0)
    render()
  }
  const box = (w: number, h: number, d: number, x: number, y: number, z: number, color: string) => {
    const obj = new THREE.Mesh(
      new THREE.BoxGeometry(w, h, d),
      new THREE.MeshStandardMaterial({ color, roughness: 0.85 }),
    )
    obj.position.set(x, y, z)
    scene.add(obj)
    return obj
  }
  const light = new THREE.HemisphereLight('#ecf6e9', '#716049', 2.2)
  scene.add(light)
  const lamp = new THREE.DirectionalLight('#ffdcab', 2)
  lamp.position.set(1, 4, 2)
  scene.add(lamp)
  box(11, 0.1, 10, 0, -0.05, 0, '#55473d')
  box(11, 4.6, 0.12, 0, 2.3, -4, finish.wall)
  box(0.15, 4.6, 10, -5.4, 2.3, 0, finish.wall)
  box(0.15, 4.6, 10, 5.4, 2.3, 0, finish.wall)
  box(11, 0.14, 10, 0, 4.65, 0, '#31302a')
  box(11, 4.6, 0.1, 0, 2.3, 5, '#303731')
  for (const x of [-4.7, -2.3, 0, 2.3, 4.7]) box(0.065, 4.5, 0.12, x, 2.25, -3.85, '#79644f')
  box(9.4, 0.1, 0.45, 0, 0.82, -3.42, finish.wood)
  box(9.4, 0.08, 0.3, 0, 3.55, -3.65, accent)
  box(2.3, 0.5, 0.85, 2.7, 0.25, 1.2, '#796450')
  box(2.3, 0.62, 0.18, 2.7, 0.65, 1.62, '#796450')
  box(1.0, 0.08, 0.66, -2.5, 0.72, 1, '#aa8262')
  box(0.2, 0.7, 0.25, -2.5, 0.35, 1, '#554336')
  const loader = new THREE.TextureLoader()
  function plane(
    w: number,
    h: number,
    x: number,
    y: number,
    z: number,
    angle: number,
    texture: THREE.Texture,
    action?: string,
  ) {
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ map: texture }),
    )
    mesh.position.set(x, y, z)
    mesh.rotation.y = angle
    gallery.add(mesh)
    if (action) {
      mesh.userData.action = action
      targets.push(mesh)
    }
    return mesh
  }
  function imagePanel(
    mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>,
    url: string,
    version: number,
  ) {
    let safe: URL
    try {
      safe = new URL(url, location.href)
    } catch {
      return
    }
    if (safe.origin !== location.origin || !/^https?:$/.test(safe.protocol)) return
    loader.load(
      safe.href,
      (tex) => {
        if (disposed || version !== revision) {
          tex.dispose()
          return
        }
        tex.colorSpace = THREE.SRGBColorSpace
        const { width, height } = tex.image
        const ratio =
          width / height / (mesh.geometry.parameters.width / mesh.geometry.parameters.height)
        if (ratio > 1) {
          tex.repeat.x = 1 / ratio
          tex.offset.x = (1 - tex.repeat.x) / 2
        } else {
          tex.repeat.y = ratio
          tex.offset.y = (1 - tex.repeat.y) / 2
        }
        const previous = mesh.material.map
        if (previous) {
          previous.dispose()
        }
        mesh.material.map = tex
        mesh.material.needsUpdate = true
        render()
      },
      undefined,
      () => {},
    )
  }
  function clearGallery() {
    targets.length = 0
    for (const child of gallery.children) {
      const m = child as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>
      m.material.map?.dispose()
      m.material.dispose()
      m.geometry.dispose()
    }
    gallery.clear()
  }
  function update(next: RoomView) {
    if (currentView?.selected?.uuid !== next.selected?.uuid) readingPage = 0
    const comfortChanged = currentView?.comfort !== next.comfort
    currentView = next
    if (comfortChanged) move(station)
    const version = ++revision
    clearGallery()
    function sign(
      w: number,
      h: number,
      x: number,
      y: number,
      z: number,
      a: number,
      title: string,
      copy: string,
      action?: string,
    ) {
      return plane(w, h, x, y, z, a, labelTexture(title, copy, accent, w / h), action)
    }
    sign(3.4, 0.62, 0, 3.06, -3.78, 0, 'Library wall', next.shelf)
    sign(
      1.48,
      0.6,
      -3.3,
      3.06,
      -3.76,
      0,
      next.collection ? 'VR titles' : 'Full library',
      'Switch catalog',
      '@scope',
    )
    sign(1.48, 0.6, 3.3, 3.06, -3.76, 0, 'Recenter', 'Reset view', '@home')
    next.games.forEach((g, i) => {
      const x = (i - (next.games.length - 1) / 2) * 1.48
      const art = sign(
        1.19,
        1.32,
        x,
        1.99,
        -3.55,
        0,
        g.name,
        g.vr_compat === 'native_vr' ? 'Native VR' : 'Game',
        g.uuid,
      )
      if (g.cover_url && !g.cover_url.endsWith('default_cover.jpg'))
        imagePanel(art, g.cover_url, version)
      sign(1.34, 0.59, x, 1.03, -3.48, 0, g.name, 'Read details', g.uuid)
    })
    sign(1.15, 0.5, -2.6, 0.48, -3.35, 0, 'Reading desk', 'Visit', '@reading')
    if (next.previous) sign(1.05, 0.47, -1.05, 0.48, -3.35, 0, 'Previous', 'Shelf', '@previous')
    if (next.next) sign(1.05, 0.47, 1.05, 0.48, -3.35, 0, 'Next', 'Shelf', '@next')
    sign(1.15, 0.5, 2.6, 0.48, -3.35, 0, 'Lounge', 'Visit', '@lounge')
    const reading = readingTexture(
      next.selected?.name || 'Reading desk',
      next.detailMessage ||
        next.selected?.summary ||
        (next.selected ? 'No summary available.' : 'Select a title on the library wall.'),
      readingPage,
      accent,
      next.largeText,
    )
    readingPage = reading.page
    readingPageCount = reading.pages
    plane(3.9, 1.5, -5.24, 1.85, -0.95, Math.PI / 2, reading.texture)
    sign(1.25, 0.5, -5.18, 0.79, 0.32, Math.PI / 2, 'Library wall', 'Return', '@library')
    if (next.selected)
      sign(
        1.35,
        0.5,
        -5.18,
        0.79,
        -1,
        Math.PI / 2,
        next.selected.is_favorite ? 'Remove favorite' : 'Add favorite',
        next.favoriteMessage || 'Your library',
        '@favorite',
      )
    sign(1.2, 0.38, -5.18, 2.9, 0.15, Math.PI / 2, 'Recenter', 'Reset view', '@home')
    sign(
      1.2,
      0.38,
      -5.18,
      2.9,
      -1.35,
      Math.PI / 2,
      'Text size',
      next.largeText ? 'Large' : 'Standard',
      '@text',
    )
    sign(1.2, 0.38, 5.18, 2.9, -1.0, -Math.PI / 2, 'Recenter', 'Reset view', '@home')
    if (reading.pages > 1) {
      if (reading.page > 0)
        sign(0.98, 0.44, -5.18, 0.34, 0.1, Math.PI / 2, 'Previous', 'Page', '@read-back')
      if (reading.page + 1 < reading.pages)
        sign(0.98, 0.44, -5.18, 0.34, -1.25, Math.PI / 2, 'Next', 'Page', '@read-next')
    }
    const slug = document.documentElement.dataset.theme || ''
    const artSlug = roomArtSlug(slug)
    const art = sign(3.8, 2.0, 5.24, 2, -1, -Math.PI / 2, 'Lounge', '')
    imagePanel(art, '/static/newstyle/rooms/' + artSlug + '.webp', version)
    sign(
      1.45,
      0.45,
      5.18,
      1.42,
      -1.0,
      -Math.PI / 2,
      'Comfort',
      next.comfort || 'Standard',
      '@comfort',
    )
    if (activeSession) sign(1.1, 0.5, 3.85, 0.48, -3.35, 0, 'Exit XR', 'End session', '@exit')
    sign(1.48, 0.54, 5.18, 0.72, -1.83, -Math.PI / 2, 'Library wall', 'Return', '@library')
    sign(1.48, 0.54, 5.18, 0.72, -0.17, -Math.PI / 2, 'Favorite shelf', 'Your titles', '@favorites')
    render()
  }
  function activate() {
    const hit = ray.intersectObjects(targets, false)[0]?.object.userData.action as
      string | undefined
    if (!hit) return
    if ((hit === '@read-back' || hit === '@read-next') && currentView) {
      readingPage = THREE.MathUtils.clamp(
        readingPage + (hit === '@read-next' ? 1 : -1),
        0,
        readingPageCount - 1,
      )
      update(currentView)
      return
    }
    if (hit === '@home') {
      move(station)
      return
    }
    if (hit === '@exit') {
      void activeSession?.end()
      return
    }
    if (['@library', '@reading', '@lounge'].includes(hit)) {
      move(hit.slice(1) as Station)
      return
    }
    select(hit)
    if (!hit.startsWith('@')) move('reading')
  }
  let down: {
    x: number
    y: number
    yaw: number
    pitch: number
    id: number
    dragged: boolean
  } | null = null
  function pointerDown(e: PointerEvent) {
    if (e.button !== 0 || down || activeSession) return
    down = {
      x: e.clientX,
      y: e.clientY,
      yaw,
      pitch: camera.rotation.x,
      id: e.pointerId,
      dragged: false,
    }
    canvas.setPointerCapture(e.pointerId)
  }
  function pointerMove(e: PointerEvent) {
    if (!down || down.id !== e.pointerId) return
    const dx = e.clientX - down.x
    const dy = e.clientY - down.y
    if (!down.dragged && Math.hypot(dx, dy) <= 8) return
    down.dragged = true
    yaw = down.yaw - dx * 0.005
    camera.rotation.set(THREE.MathUtils.clamp(down.pitch - dy * 0.005, -1.1, 1.1), yaw, 0)
    render()
  }
  function pointerCancel(e: PointerEvent) {
    if (down?.id === e.pointerId) down = null
  }
  function pointerUp(e: PointerEvent) {
    if (!down || down.id !== e.pointerId) return
    pointerMove(e)
    const dragged = down.dragged
    down = null
    if (dragged) return
    const r = canvas.getBoundingClientRect()
    ray.setFromCamera(
      new THREE.Vector2(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        1 - ((e.clientY - r.top) / r.height) * 2,
      ),
      camera,
    )
    activate()
  }
  function key(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey || e.altKey || activeSession) return
    if (
      ['w', 'a', 's', 'd', 'arrowleft', 'arrowright', 'arrowup', 'arrowdown', 'home'].includes(
        e.key.toLowerCase(),
      )
    )
      e.stopPropagation()
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      yaw = yaw + (e.key === 'ArrowLeft' ? 0.16 : -0.16)
      camera.rotation.y = yaw
      render()
    }
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      camera.rotation.x = THREE.MathUtils.clamp(
        camera.rotation.x + (e.key === 'ArrowUp' ? 0.12 : -0.12),
        -1.1,
        1.1,
      )
      render()
    }
    const direction = { w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0] }[e.key.toLowerCase()]
    if (direction) {
      e.preventDefault()
      const step = new THREE.Vector3(direction[0], 0, direction[1]).applyAxisAngle(
        new THREE.Vector3(0, 1, 0),
        rig.rotation.y + yaw,
      )
      rig.position.addScaledVector(step, 0.22)
      rig.position.x = THREE.MathUtils.clamp(rig.position.x, -4.6, 4.6)
      rig.position.z = THREE.MathUtils.clamp(rig.position.z, -2.9, 4.1)
      render()
    }
    if (e.key === 'Home') {
      e.preventDefault()
      move(station)
    }
  }
  function contextLost(e: Event) {
    e.preventDefault()
    report('The graphics connection closed. Reopen the room or continue in the catalog.')
  }
  canvas.addEventListener('pointerdown', pointerDown)
  canvas.addEventListener('pointerup', pointerUp)
  canvas.addEventListener('pointermove', pointerMove)
  canvas.addEventListener('pointercancel', pointerCancel)
  canvas.addEventListener('lostpointercapture', pointerCancel)
  canvas.addEventListener('keydown', key)
  canvas.addEventListener('webglcontextlost', contextLost)
  const observers = new ResizeObserver(resize)
  observers.observe(canvas)
  const controllerCleanups: (() => void)[] = []
  for (const index of [0, 1]) {
    const controller = renderer.xr.getController(index)
    rig.add(controller)
    const pointer = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, -5)]),
      new THREE.LineBasicMaterial({ color: accent }),
    )
    controller.add(pointer)
    function onSelect() {
      controller.updateWorldMatrix(true, false)
      ray.setFromXRController(controller)
      activate()
    }
    controller.addEventListener('select', onSelect)
    controllerCleanups.push(() => controller.removeEventListener('select', onSelect))
  }
  async function enter() {
    if (!navigator.xr || disposed) return
    const session = await navigator.xr.requestSession('immersive-vr', {
      requiredFeatures: ['local-floor'],
    })
    if (disposed) {
      await session.end()
      return
    }
    activeSession = session
    const end = () => {
      activeSession = null
      renderer.setAnimationLoop(null)
      if (!disposed) {
        changeSession(false)
        if (currentView) update(currentView)
        move(station)
        resize()
      }
    }
    session.addEventListener('end', end, { once: true })
    try {
      await renderer.xr.setSession(session)
      if (disposed) return
      renderer.setAnimationLoop(() => renderer.render(scene, camera))
      if (currentView) update(currentView)
      changeSession(true)
    } catch (error) {
      await session.end().catch(() => {})
      throw error
    }
  }
  move('library')
  resize()
  return {
    recenter: () => move(station),
    update,
    move,
    enter,
    exit: () => activeSession?.end(),
    dispose() {
      disposed = true
      revision++
      renderer.setAnimationLoop(null)
      void activeSession?.end().catch(() => {})
      controllerCleanups.forEach((f) => f())
      observers.disconnect()
      canvas.removeEventListener('pointerdown', pointerDown)
      canvas.removeEventListener('pointerup', pointerUp)
      canvas.removeEventListener('pointermove', pointerMove)
      canvas.removeEventListener('pointercancel', pointerCancel)
      canvas.removeEventListener('lostpointercapture', pointerCancel)
      canvas.removeEventListener('keydown', key)
      canvas.removeEventListener('webglcontextlost', contextLost)
      clearGallery()
      scene.traverse((o) => {
        if (o instanceof THREE.InstancedMesh) o.dispose()
        if (o instanceof THREE.Mesh || o instanceof THREE.Line) {
          o.geometry.dispose()
          const m = o.material
          if (Array.isArray(m)) m.forEach((x) => x.dispose())
          else m.dispose()
        }
      })
      renderer.dispose()
      renderer.forceContextLoss()
    },
  }
}
