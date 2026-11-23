import * as THREE from 'three'
import { createMoonfallAudio } from './pinball/audio'
import { readingTexture } from './roomReading'
import { furnishRoom, roomFinish, roomArtSlug } from './roomFurnishings'
import { furnishObservatory } from './roomObservatory'
import { createPinballTable } from './pinball/render'
import { createPinballRuntime } from './pinball/runtime'
import type { MoonfallSnapshot } from './pinball/runtime'
import type { MoonfallInput } from './pinball/model'
import { bindPinballControls } from './pinball/controls'
import { disposeRoomGroup } from './roomGeometry'

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
export type Station = 'library' | 'reading' | 'lounge' | 'pinball'
export interface RoomOptions {
  theme?: string
  onGameSnapshot?: (snapshot: MoonfallSnapshot) => void
  onGameCommand?: (action: 'pause' | 'resume') => void
}
export interface RoomGameMenu {
  title: string
  message: string
  actions: { label: string; action: string; disabled?: boolean }[]
}

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
  options: RoomOptions = {},
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
  const theme = options.theme || document.documentElement.dataset.theme || 'default'
  const world = roomArtSlug(theme)
  const finish = roomFinish(theme)
  const observatory = world === 'oneirodex' ? furnishObservatory(scene) : null
  if (!observatory) furnishRoom(scene, theme)
  const gallery = new THREE.Group()
  scene.add(gallery)
  const targets: THREE.Mesh[] = []
  const ray = new THREE.Raycaster()
  let disposed = false
  let graphicsLost = false
  let windowFocused = true
  let previousFrame: number | undefined
  let lastQuality = ''
  let xrPauseHeld = false
  let gameMenu: THREE.Group | null = null
  let gameMenuKey = ''
  let gameMenuTargets: THREE.Mesh[] = []
  const gamePointers = new Map<
    number,
    { mode: 'mouse' | 'touch' | 'target'; action: keyof MoonfallInput }
  >()
  let revision = 0
  let activeSession: XRSession | null = null
  let currentView: RoomView | undefined
  let readingPage = 0
  let readingPageCount = 1
  let station: Station = 'library'
  let yaw = 0
  const audio = observatory ? createMoonfallAudio() : null
  const gameRuntime = observatory
    ? createPinballRuntime((snapshot) => {
        if (snapshot.status !== 'running') gamePointers.clear()
        audio?.observe(snapshot.state, snapshot.status)
        if (!disposed) options.onGameSnapshot?.(snapshot)
      })
    : null
  const table = observatory ? createPinballTable() : null
  if (table) scene.add(table.group)
  const gameTargets = table
    ? [...table.actionMeshes, table.group.getObjectByName('pinball-cabinet') as THREE.Mesh]
    : []
  const instrumentTargets = observatory?.actionMeshes || []
  if (table) gameTargets[gameTargets.length - 1].userData.action = '@moonfall-open'
  const gameControls = gameRuntime
    ? bindPinballControls(
        canvas,
        gameRuntime,
        () => Boolean(activeSession),
        (action) => options.onGameCommand?.(action),
      )
    : null
  const render = () => {
    if (!disposed && !graphicsLost && !renderer.xr.isPresenting) {
      if (gameRuntime) table?.update(gameRuntime.readState())
      renderer.render(scene, camera)
    }
  }
  function animate(time: number) {
    if (disposed || graphicsLost || !Number.isFinite(time)) return
    const seconds = previousFrame === undefined ? 0 : Math.max(0, (time - previousFrame) / 1000)
    previousFrame = time
    gameControls?.pollGamepads()
    if (activeSession && gameRuntime) {
      const visible = !activeSession.visibilityState || activeSession.visibilityState === 'visible'
      const sources = Array.from(activeSession.inputSources || [])
      const pressed = (button: number) =>
        visible && sources.some((source) => Boolean(source.gamepad?.buttons[button]?.pressed))
      const pause = pressed(5)
      if (pause && !xrPauseHeld) {
        if (gameRuntime.status() === 'running') options.onGameCommand?.('pause')
        else if (gameRuntime.status() === 'paused' && !graphicsLost)
          options.onGameCommand?.('resume')
      }
      xrPauseHeld = pause
      gameRuntime.input('launch', pressed(4), 'xr-buttons')
    }
    if (station === 'pinball') gameRuntime?.tick(seconds)
    else gameRuntime?.pause()
    if (gameRuntime) {
      const state = gameRuntime.readState()
      observatory?.update(time / 1000, state.settings.reducedMotion)
      observatory?.setQuality(state.settings.quality)
      if (lastQuality !== state.settings.quality) {
        lastQuality = state.settings.quality
        renderer.shadowMap.enabled = lastQuality !== 'low'
        if (!renderer.xr.isPresenting)
          renderer.setPixelRatio(
            Math.min(
              window.devicePixelRatio || 1,
              lastQuality === 'low' ? 1 : lastQuality === 'high' ? 1.6 : 1.3,
            ),
          )
      }
      table?.update(state)
    }
    renderer.render(scene, camera)
  }
  function refreshLoop() {
    previousFrame = undefined
    const sleeping = activeSession
      ? activeSession.visibilityState === 'hidden'
      : !windowFocused || document.visibilityState === 'hidden'
    renderer.setAnimationLoop(
      !disposed && !graphicsLost && !sleeping && (observatory || activeSession) ? animate : null,
    )
  }
  const resize = () => {
    if (disposed || renderer.xr.isPresenting) return
    const { width, height } = canvas.getBoundingClientRect()
    if (!width || !height) return
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    if (station === 'pinball' && !activeSession) move('pinball')
    else render()
  }
  const positions: Record<Station, [number, number, number]> = {
    library: [0, 0, 2.1],
    reading: [-2.65, 0, -0.95],
    lounge: [2.65, 0, -0.95],
    pinball: [0, 0, 2.5],
  }
  function move(next: Station) {
    if (next === 'pinball' && !gameRuntime) return
    if (next !== 'pinball') gameRuntime?.pause()
    station = next
    if (gameMenu) gameMenu.visible = next === 'pinball'
    yaw = 0
    rig.position.set(...positions[next])
    const mode = currentView?.comfort
    if (mode === 'Seated') rig.position.y += 0.38
    if (mode === 'Close reach') {
      if (next === 'library') rig.position.z -= 0.8
      else if (next !== 'pinball') rig.position.x += next === 'reading' ? -0.65 : 0.65
    }
    rig.rotation.y = next === 'reading' ? Math.PI / 2 : next === 'lounge' ? -Math.PI / 2 : 0
    camera.position.set(0, 1.55, 0)
    camera.rotation.set(0, 0, 0)
    if (next === 'library' && observatory && !activeSession) {
      // Desktop overview clears the cabinet backboard without moving the XR rig.
      camera.position.y = 4.2 - rig.position.y
      camera.rotation.x = -Math.atan2(2.35, rig.position.z + 3.55)
    }
    if (next === 'pinball' && !activeSession) {
      const back = 3.4 + Math.max(0, 1 - camera.aspect) * 1.5
      rig.position.z = back
      camera.position.y = 2.7 - rig.position.y
      camera.rotation.x = -Math.atan2(1.6, back + 0.2)
    }
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
  if (observatory) {
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.1
  } else {
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
  }
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
    if (!observatory) {
      const art = sign(3.8, 2.0, 5.24, 2, -1, -Math.PI / 2, 'Lounge', '')
      imagePanel(art, '/static/newstyle/rooms/' + world + '.webp', version)
    }
    if (gameRuntime)
      sign(1.45, 0.48, 0, 2.4, -1.57, 0, 'Moonfall Pinball', 'Visit the table', '@moonfall-open')
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
    const hit = ray.intersectObjects(
      [
        ...targets,
        ...gameTargets,
        ...(station === 'pinball' ? gameMenuTargets : []),
        ...instrumentTargets,
      ],
      false,
    )[0]?.object.userData.action as string | undefined
    if (!hit) return
    if (hit === '@instrument-telescope' || hit === '@instrument-orrery') {
      gameRuntime?.pause()
      observatory?.interact(hit.slice('@instrument-'.length) as 'telescope' | 'orrery')
      render()
      return
    }
    if (hit.startsWith('@moonfall-') || hit.startsWith('@pinball-')) {
      move('pinball')
      select(hit.startsWith('@pinball-') ? '@moonfall-open' : hit)
      return
    }
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
    if (activeSession) return
    if (
      station === 'pinball' &&
      gameRuntime?.status() === 'running' &&
      (e.button === 0 || e.button === 2)
    ) {
      if (!pointerRay(e)) return
      const hit = ray.intersectObjects(
        [...targets, ...gameTargets, ...(station === 'pinball' ? gameMenuTargets : [])],
        false,
      )[0]?.object.userData.action as string | undefined
      const menu = hit?.startsWith('@moonfall-') && hit !== '@moonfall-open'
      if (!menu) {
        e.preventDefault()
        canvas.focus()
        const chosen = hit?.startsWith('@pinball-') ? hit.slice('@pinball-'.length) : null
        const touch = e.pointerType === 'touch'
        const action =
          chosen === 'left' || chosen === 'right' || chosen === 'launch'
            ? chosen
            : touch
              ? e.clientX <
                canvas.getBoundingClientRect().left + canvas.getBoundingClientRect().width / 2
                ? 'left'
                : 'right'
              : e.button === 2
                ? 'right'
                : 'left'
        gamePointers.set(e.pointerId, {
          mode: chosen ? 'target' : touch ? 'touch' : 'mouse',
          action,
        })
        gameRuntime.input(action, true, 'canvas-pointer:' + e.pointerId)
        canvas.setPointerCapture?.(e.pointerId)
        return
      }
    }
    if (e.button !== 0 || down) return
    down = {
      x: e.clientX,
      y: e.clientY,
      yaw,
      pitch: camera.rotation.x,
      id: e.pointerId,
      dragged: false,
    }
    canvas.setPointerCapture?.(e.pointerId)
  }
  function pointerMove(e: PointerEvent) {
    const pressed = gamePointers.get(e.pointerId)
    if (pressed && gameRuntime) {
      if (pressed.mode === 'mouse') {
        gameRuntime.input('left', Boolean(e.buttons & 1), 'canvas-pointer:' + e.pointerId)
        gameRuntime.input('right', Boolean(e.buttons & 2), 'canvas-pointer:' + e.pointerId)
      }
      return
    }
    if (!down || down.id !== e.pointerId) return
    const dx = e.clientX - down.x
    const dy = e.clientY - down.y
    if (!down.dragged && Math.hypot(dx, dy) <= 8) return
    down.dragged = true
    if (station === 'pinball' && gameRuntime?.status() === 'running') return
    yaw = down.yaw - dx * 0.005
    camera.rotation.set(THREE.MathUtils.clamp(down.pitch - dy * 0.005, -1.1, 1.1), yaw, 0)
    render()
  }
  function pointerCancel(e: PointerEvent) {
    gameRuntime?.releaseSource('canvas-pointer:' + e.pointerId)
    gamePointers.delete(e.pointerId)
    if (down?.id === e.pointerId) down = null
  }
  function pointerUp(e: PointerEvent) {
    if (gamePointers.has(e.pointerId)) {
      pointerCancel(e)
      return
    }
    if (!down || down.id !== e.pointerId) return
    pointerMove(e)
    const dragged = down.dragged
    down = null
    if (dragged) return
    if (!pointerRay(e)) return
    activate()
  }
  function pointerRay(e: { clientX: number; clientY: number }) {
    const r = canvas.getBoundingClientRect()
    if (!r.width || !r.height) return false
    camera.updateWorldMatrix(true, false)
    ray.setFromCamera(
      new THREE.Vector2(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        1 - ((e.clientY - r.top) / r.height) * 2,
      ),
      camera,
    )
    return true
  }
  function key(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey || e.altKey || activeSession) return
    if (station === 'pinball' && gameRuntime?.status() === 'running') return
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
      const next = rig.position.clone().addScaledVector(step, 0.22)
      if (observatory && !observatory.canStandAt(next.x, next.z)) return
      rig.position.copy(next)
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
    if (disposed) return
    graphicsLost = true
    gameRuntime?.pause()
    refreshLoop()
    report('The graphics connection closed. Reopen the room or continue in the catalog.')
  }
  canvas.addEventListener('pointerdown', pointerDown)
  canvas.addEventListener('pointerup', pointerUp)
  canvas.addEventListener('pointermove', pointerMove)
  canvas.addEventListener('pointercancel', pointerCancel)
  canvas.addEventListener('lostpointercapture', pointerCancel)
  canvas.addEventListener('keydown', key)
  canvas.addEventListener('webglcontextlost', contextLost)
  const contextMenu = (e: Event) => {
    if (station === 'pinball' && gameRuntime?.status() === 'running') e.preventDefault()
  }
  canvas.addEventListener('contextmenu', contextMenu)
  window.addEventListener('pointerup', pointerCancel)
  const blur = () => {
    if (!activeSession) {
      windowFocused = false
      gameRuntime?.pause()
      refreshLoop()
    }
  }
  const focus = () => {
    windowFocused = true
    refreshLoop()
  }
  const visibility = () => {
    if (!activeSession && document.visibilityState === 'hidden') gameRuntime?.pause()
    refreshLoop()
  }
  window.addEventListener('blur', blur)
  window.addEventListener('focus', focus)
  document.addEventListener('visibilitychange', visibility)
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
    let handedness: XRHandedness = index === 0 ? 'left' : 'right'
    let triggerWasGameInput = false
    const source = 'xr-controller:' + index
    function onConnected(event: { data: XRInputSource }) {
      handedness = event.data.handedness
    }
    function onStart() {
      triggerWasGameInput = false
      if (!gameRuntime || station !== 'pinball' || gameRuntime.status() !== 'running') return
      if (activeSession?.visibilityState && activeSession.visibilityState !== 'visible') return
      controller.updateWorldMatrix(true, false)
      ray.setFromXRController(controller)
      const action = ray.intersectObjects(
        [...targets, ...gameTargets, ...(station === 'pinball' ? gameMenuTargets : [])],
        false,
      )[0]?.object.userData.action as string | undefined
      if (
        action?.startsWith('@instrument-') ||
        action?.startsWith('@moonfall-') ||
        ['@library', '@reading', '@lounge', '@exit', '@home'].includes(action || '')
      )
        return
      const button = action?.startsWith('@pinball-')
        ? action.slice('@pinball-'.length)
        : handedness === 'right'
          ? 'right'
          : 'left'
      if (button === 'left' || button === 'right' || button === 'launch') {
        gameRuntime.input(button, true, source)
        triggerWasGameInput = true
      }
    }
    function onEnd() {
      gameRuntime?.releaseSource(source)
    }
    function onDisconnected() {
      onEnd()
      gameRuntime?.pause()
    }
    function onSelect() {
      if (triggerWasGameInput) return
      controller.updateWorldMatrix(true, false)
      ray.setFromXRController(controller)
      activate()
    }
    controller.addEventListener('select', onSelect)
    controller.addEventListener('selectstart', onStart)
    controller.addEventListener('selectend', onEnd)
    controller.addEventListener('connected', onConnected)
    controller.addEventListener('disconnected', onDisconnected)
    controllerCleanups.push(() => {
      controller.removeEventListener('select', onSelect)
      controller.removeEventListener('selectstart', onStart)
      controller.removeEventListener('selectend', onEnd)
      controller.removeEventListener('connected', onConnected)
      controller.removeEventListener('disconnected', onDisconnected)
      onEnd()
    })
  }
  async function enter() {
    if (!navigator.xr || disposed) return
    gameRuntime?.pause()
    const session = await navigator.xr.requestSession('immersive-vr', {
      requiredFeatures: ['local-floor'],
    })
    if (disposed) {
      await session.end()
      return
    }
    activeSession = session
    const visibilityChanged = () => {
      if (session.visibilityState !== 'visible') {
        gameRuntime?.pause()
        xrPauseHeld = true
      }
      refreshLoop()
    }
    const end = () => {
      session.removeEventListener('visibilitychange', visibilityChanged)
      activeSession = null
      gameRuntime?.pause()
      refreshLoop()
      if (!disposed) {
        changeSession(false)
        if (currentView) update(currentView)
        move(station)
        resize()
      }
    }
    session.addEventListener('end', end, { once: true })
    session.addEventListener('visibilitychange', visibilityChanged)
    try {
      await renderer.xr.setSession(session)
      if (disposed) return
      move(station)
      refreshLoop()
      if (currentView) update(currentView)
      changeSession(true)
    } catch (error) {
      await session.end().catch(() => {})
      throw error
    }
  }
  move('library')
  resize()
  refreshLoop()
  function setGameMenu(menu: RoomGameMenu) {
    if (!gameRuntime || disposed) return
    const key = JSON.stringify(menu)
    if (gameMenuKey === key) return
    gameMenuKey = key
    if (gameMenu) disposeRoomGroup(gameMenu)
    gameMenu = new THREE.Group()
    gameMenu.name = 'moonfall-instrument-menu'
    gameMenu.visible = station === 'pinball'
    gameMenuTargets = []
    scene.add(gameMenu)
    function panel(
      w: number,
      h: number,
      y: number,
      title: string,
      subtitle: string,
      action?: string,
    ) {
      const texture = labelTexture(title, subtitle, accent, w / h)
      const item = new THREE.Mesh(
        new THREE.PlaneGeometry(w, h),
        new THREE.MeshBasicMaterial({ map: texture }),
      )
      item.position.set(1.4, y, 0.35)
      item.rotation.y = -0.25
      gameMenu!.add(item)
      if (action) {
        item.userData.action = action
        gameMenuTargets.push(item)
      }
    }
    panel(1.12, 0.85, 2.05, menu.title, menu.message)
    menu.actions
      .slice(0, 5)
      .forEach((action, i) =>
        panel(
          1.12,
          0.24,
          1.48 - i * 0.28,
          action.label,
          action.disabled ? 'Unavailable' : '',
          action.disabled ? undefined : action.action,
        ),
      )
    render()
  }
  const game = gameRuntime
    ? {
        start() {
          if (!disposed && !graphicsLost) {
            move('pinball')
            gameRuntime.start()
            audio?.unlock(gameRuntime.readState().settings)
            canvas.focus()
          }
        },
        resume() {
          if (!disposed && !graphicsLost) {
            move('pinball')
            gameRuntime.resume()
            audio?.unlock(gameRuntime.readState().settings)
            canvas.focus()
          }
        },
        restore: gameRuntime.restore,
        pause: gameRuntime.pause,
        input: gameRuntime.input,
        releaseSource: gameRuntime.releaseSource,
        snapshot: gameRuntime.snapshot,
        status: gameRuntime.status,
        setSettings(value: Parameters<typeof gameRuntime.setSettings>[0]) {
          gameRuntime.setSettings(value)
          audio?.unlock(gameRuntime.readState().settings)
        },
        deny() {
          audio?.dispose()
          gameRuntime.dispose()
          gamePointers.clear()
          setGameMenu({
            title: 'Moonfall Pinball',
            message: 'Sign in again or reopen the room to restore access.',
            actions: [],
          })
          render()
        },
      }
    : null
  return {
    game,
    instrument(kind: 'telescope' | 'orrery') {
      gameRuntime?.pause()
      observatory?.interact(kind)
      render()
    },
    setGameMenu,
    recenter: () => move(station),
    update,
    move,
    enter,
    exit: () => activeSession?.end(),
    dispose() {
      disposed = true
      revision++
      renderer.setAnimationLoop(null)
      gameControls?.dispose()
      gameRuntime?.dispose()
      audio?.dispose()
      table?.dispose()
      observatory?.dispose()
      if (gameMenu) disposeRoomGroup(gameMenu)
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
      canvas.removeEventListener('contextmenu', contextMenu)
      window.removeEventListener('pointerup', pointerCancel)
      window.removeEventListener('blur', blur)
      window.removeEventListener('focus', focus)
      document.removeEventListener('visibilitychange', visibility)
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
