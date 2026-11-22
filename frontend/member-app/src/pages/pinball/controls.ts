import type { MoonfallInput } from './model'
import type { PinballRuntime } from './runtime'

const bindings: Record<string, keyof MoonfallInput> = {
  KeyZ: 'left',
  ArrowLeft: 'left',
  KeyX: 'right',
  Slash: 'right',
  ArrowRight: 'right',
  Space: 'launch',
  KeyR: 'recover',
}

/** Scoped desktop controls; XR trigger/visibility handling belongs to the XR scene. */
export function bindPinballControls(
  canvas: HTMLCanvasElement,
  runtime: PinballRuntime,
  immersive: () => boolean = () => false,
  command: (action: 'pause' | 'resume') => void = (action) => runtime[action](),
) {
  const root = canvas.closest('.od-library-room') || canvas
  let disposed = false
  let startHeld = false
  function keyDown(event: KeyboardEvent) {
    if (disposed || immersive() || event.metaKey || event.ctrlKey || event.altKey) return
    if (!(event.target instanceof Node) || !root.contains(event.target)) return
    const target = event.target instanceof HTMLElement ? event.target : null
    if (target?.closest('input, select, textarea, [contenteditable="true"]')) return
    if (event.code === 'Escape' && runtime.status() === 'running') {
      event.preventDefault()
      event.stopPropagation()
      runtime.pause()
      return
    }
    if (runtime.status() !== 'running') return
    if (event.code === 'Space' && target?.closest('button')) return
    const action = bindings[event.code]
    if (!action) return
    event.preventDefault()
    event.stopPropagation()
    if (event.repeat && (action === 'launch' || action === 'recover')) return
    runtime.input(action, true, 'key:' + event.code)
  }
  function keyUp(event: KeyboardEvent) {
    if (bindings[event.code]) runtime.releaseSource('key:' + event.code)
  }
  function blur() {
    startHeld = true
    if (!immersive()) runtime.pause()
  }
  function focusOut(event: Event) {
    const target = (event as FocusEvent).relatedTarget
    if (!immersive() && (!(target instanceof Node) || !root.contains(target))) runtime.pause()
  }
  function visibility() {
    if (document.visibilityState === 'hidden' && !immersive()) runtime.pause()
  }
  root.addEventListener('keydown', keyDown as EventListener)
  root.addEventListener('focusout', focusOut)
  window.addEventListener('keyup', keyUp)
  window.addEventListener('blur', blur)
  document.addEventListener('visibilitychange', visibility)
  return {
    pollGamepads() {
      if (disposed || immersive() || !root.contains(document.activeElement)) {
        runtime.releaseSource('gamepad')
        return
      }
      let gamepad: Gamepad | undefined
      try {
        gamepad = [...(navigator.getGamepads?.() || [])].find((pad): pad is Gamepad =>
          Boolean(pad?.connected && pad.mapping === 'standard'),
        )
      } catch {
        runtime.releaseSource('gamepad')
        return
      }
      if (!gamepad) {
        runtime.releaseSource('gamepad')
        startHeld = false
        return
      }
      const pressed = (index: number) =>
        Boolean(gamepad!.buttons[index]?.pressed || gamepad!.buttons[index]?.value > 0.5)
      const start = pressed(9)
      if (start && !startHeld) {
        if (runtime.status() === 'running') command('pause')
        else if (runtime.status() === 'paused') command('resume')
      }
      startHeld = start
      runtime.input('left', pressed(4) || pressed(6), 'gamepad')
      runtime.input('right', pressed(5) || pressed(7), 'gamepad')
      runtime.input('launch', pressed(0), 'gamepad')
      runtime.input('recover', pressed(11), 'gamepad')
    },
    dispose() {
      if (disposed) return
      disposed = true
      root.removeEventListener('keydown', keyDown as EventListener)
      root.removeEventListener('focusout', focusOut)
      window.removeEventListener('keyup', keyUp)
      window.removeEventListener('blur', blur)
      document.removeEventListener('visibilitychange', visibility)
      runtime.pause()
    },
  }
}
