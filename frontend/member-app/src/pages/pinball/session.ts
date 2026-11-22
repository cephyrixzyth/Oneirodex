import { newMoonfall } from './model'
import type { PinballRuntime, MoonfallSnapshot } from './runtime'
import { loadMoonfallProgress, saveMoonfallProgress, resetMoonfallProgress } from './progress'
import type { SavedMoonfall } from './progress'

export interface MoonfallProgressApi {
  load(signal?: AbortSignal): Promise<SavedMoonfall>
  save(revision: number, state: unknown, signal?: AbortSignal): Promise<SavedMoonfall>
  reset(revision: number, signal?: AbortSignal): Promise<SavedMoonfall>
}
type Game = Pick<
  PinballRuntime,
  'snapshot' | 'status' | 'start' | 'restore' | 'pause' | 'resume' | 'setSettings' | 'input'
> & { deny(): void }
const signature = (value: unknown) => JSON.stringify(value)

/** Owns one member's in-memory run. No browser storage and no implicit restore. */
export function createMoonfallSession(
  game: Game,
  memberId: string,
  changed: () => void,
  api: MoonfallProgressApi = {
    load: loadMoonfallProgress,
    save: saveMoonfallProgress,
    reset: resetMoonfallProgress,
  },
) {
  let alive = true
  let listener: (() => void) | null = changed
  let revision: number | null = null
  let saved: SavedMoonfall | null = null
  let acknowledged = ''
  let chosen = false
  let practice = false
  let menuPage: 'main' | 'comfort' | 'sound' | 'help' = 'main'
  let blocked = false
  let serverChoice = false
  let confirm: 'new' | 'reset' | null = null
  let status: 'loading' | 'ready' | 'saving' | 'error' | 'conflict' | 'denied' = 'loading'
  let message = 'Loading your saved run…'
  let inFlight: Promise<boolean> | null = null
  let loading: Promise<void> | null = null
  let resetting = false
  let checkpoint: ReturnType<typeof setTimeout> | undefined
  const requests = new Set<AbortController>()
  const emit = () => {
    if (alive) listener?.()
  }
  const permitted = () => alive && status !== 'denied'
  const hasUnsaved = () =>
    alive &&
    chosen &&
    !practice &&
    status !== 'denied' &&
    signature(game.snapshot()) !== acknowledged
  const canWrite = () =>
    alive && !practice && status !== 'denied' && revision !== null && !blocked && !resetting
  function clearCheckpoint() {
    clearTimeout(checkpoint)
    checkpoint = undefined
  }
  async function request<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const controller = new AbortController()
    requests.add(controller)
    const timeout = setTimeout(() => controller.abort(), 12_000)
    try {
      return await operation(controller.signal)
    } finally {
      clearTimeout(timeout)
      requests.delete(controller)
    }
  }
  function failure(error: unknown) {
    if (!alive) return
    const code = (error as { status?: number })?.status
    if (code === 401 || code === 403) {
      status = 'denied'
      message = 'Server access denied. Reauthenticate before playing.'
      chosen = false
      saved = null
      revision = null
      acknowledged = ''
      blocked = true
      clearCheckpoint()
      game.deny()
    } else {
      // Pause after setting the block so the pause callback cannot queue another write.
      blocked = true
      status = code === 409 ? 'conflict' : 'error'
      message =
        code === 409
          ? 'Another session changed this save. Choose which run to keep.'
          : 'Progress could not be saved. Your current run is still in memory.'
      clearCheckpoint()
      game.pause()
    }
    emit()
  }
  function initialize(): Promise<void> {
    if (!alive || status === 'denied') return Promise.resolve()
    if (!memberId) {
      failure({ status: 401 })
      return Promise.resolve()
    }
    if (loading) return loading
    loading = (async () => {
      try {
        const result = await request((signal) => api.load(signal))
        if (!alive) return
        saved = result
        revision = result.revision
        // A retry is a read, never permission to overwrite a different server run.
        serverChoice = chosen
        blocked = chosen
        status = 'ready'
        message = chosen
          ? 'Choose the server run or explicitly replace it with this run.'
          : result.state
            ? 'A saved run is available.'
            : 'Ready for your first run.'
        emit()
      } catch (error) {
        failure(error)
      } finally {
        loading = null
        emit()
      }
    })()
    emit()
    return loading
  }
  function flush(): Promise<boolean> {
    clearCheckpoint()
    if (inFlight) return inFlight
    if (!hasUnsaved()) return Promise.resolve(true)
    if (!canWrite()) return Promise.resolve(false)
    const state = game.snapshot()
    const expected = revision!
    const sent = signature(state)
    status = 'saving'
    message = 'Saving progress…'
    // Assign before emitting so a subscriber cannot start a competing write.
    inFlight = (async () => {
      try {
        const result = await request((signal) => api.save(expected, state, signal))
        if (!permitted()) return false
        saved = result
        revision = result.revision
        acknowledged = sent
        status = 'ready'
        message = 'Progress saved.'
        return true
      } catch (error) {
        failure(error)
        return false
      } finally {
        inFlight = null
        emit()
      }
    })()
    emit()
    return inFlight
  }
  async function beforeLeave() {
    if (!alive || status === 'denied') return true
    game.pause()
    clearCheckpoint()
    if (inFlight) await inFlight
    if (loading) await loading
    if (resetting) return false
    return (await flush()) && !hasUnsaved()
  }
  function observe(event: MoonfallSnapshot) {
    if (!permitted()) return
    emit()
    if (
      chosen &&
      canWrite() &&
      event.reason !== 'tick' &&
      event.reason !== 'restore' &&
      event.reason !== 'resume'
    ) {
      clearCheckpoint()
      checkpoint = setTimeout(() => {
        void flush()
      }, 250)
    }
  }
  async function command(action: string) {
    if (!alive || status === 'denied' || resetting) return
    if (loading && !['pause', 'cancel', 'retry'].includes(action)) return
    if (action === 'back') {
      menuPage = 'main'
      emit()
      return
    }
    if (!confirm && ['options', 'sound-options', 'help'].includes(action)) {
      menuPage = action === 'options' ? 'comfort' : action === 'sound-options' ? 'sound' : 'help'
      game.pause()
      emit()
      return
    }
    if (
      !confirm &&
      ['quality', 'motion', 'contrast', 'mute', 'volume-up', 'volume-down'].includes(action)
    ) {
      const settings = game.snapshot().settings
      if (action === 'quality') {
        const qualities = ['low', 'standard', 'high'] as const
        game.setSettings({ quality: qualities[(qualities.indexOf(settings.quality) + 1) % 3] })
      } else if (action === 'motion') game.setSettings({ reducedMotion: !settings.reducedMotion })
      else if (action === 'contrast') game.setSettings({ highContrast: !settings.highContrast })
      else if (action === 'mute') game.setSettings({ muted: !settings.muted })
      else
        game.setSettings({
          volume: Math.max(
            0,
            Math.min(
              1,
              Math.round((settings.volume + (action === 'volume-up' ? 0.1 : -0.1)) * 10) / 10,
            ),
          ),
        })
      emit()
      return
    }
    if (action === 'recover' && chosen && !confirm && game.status() === 'running') {
      game.input('recover', true, 'session')
      game.input('recover', false, 'session')
      return
    }
    if (action === 'practice') {
      if (confirm || (chosen && !(await beforeLeave()))) return
      if (!permitted()) return
      practice = true
      chosen = true
      blocked = true
      serverChoice = false
      game.restore(newMoonfall())
      game.start()
      message = 'Practice only. Your saved run and personal best are unchanged.'
      emit()
      return
    }
    if (action === 'restart-practice' && practice) {
      game.start()
      return
    }
    if (action === 'finish-practice' && practice) {
      practice = false
      chosen = false
      blocked = revision === null
      acknowledged = ''
      game.restore(newMoonfall())
      message = saved?.state ? 'A saved run is available.' : 'Practice finished.'
      emit()
      return
    }
    if (action === 'continue-unsaved' && chosen && (blocked || serverChoice)) {
      game.resume()
      emit()
      return
    }
    if (action === 'cancel') {
      confirm = null
      emit()
      return
    }
    if (action === 'retry') {
      if (inFlight) await inFlight
      await initialize()
      return
    }
    if (action === 'pause') {
      game.pause()
      return
    }
    if (action === 'save') {
      await flush()
      return
    }
    if (action === 'reset') {
      menuPage = 'main'
      game.pause()
      confirm = 'reset'
      emit()
      return
    }
    if (action === 'confirm-reset' && confirm === 'reset') {
      clearCheckpoint()
      game.pause()
      if (inFlight) await inFlight
      if (!canWrite()) return
      resetting = true
      confirm = null
      try {
        const result = await request((signal) => api.reset(revision!, signal))
        if (!alive) return
        chosen = false
        saved = result
        revision = result.revision
        acknowledged = ''
        serverChoice = false
        blocked = false
        status = 'ready'
        message = 'Saved progress reset.'
        game.restore(newMoonfall())
      } catch (error) {
        failure(error)
      } finally {
        resetting = false
        emit()
      }
      return
    }
    if (action === 'load-server' && serverChoice) {
      chosen = !!saved?.state
      if (saved?.state) game.restore(saved.state)
      else game.restore(newMoonfall())
      acknowledged = chosen ? signature(game.snapshot()) : ''
      serverChoice = false
      blocked = false
      status = 'ready'
      emit()
      return
    }
    if (action === 'replace-server' && serverChoice) {
      serverChoice = false
      blocked = false
      acknowledged = ''
      await flush()
      return
    }
    if (action === 'resume') {
      if (confirm || (!practice && (blocked || serverChoice || revision === null))) return
      if (!chosen && saved?.state) {
        game.restore(saved.state)
        chosen = true
        acknowledged = signature(game.snapshot())
      }
      if (chosen) game.resume()
      emit()
      return
    }
    if (action === 'new') {
      if (revision === null || blocked) return
      if (saved?.state || chosen) {
        game.pause()
        confirm = 'new'
        emit()
        return
      }
    } else if (action === 'confirm-new') {
      if (confirm !== 'new' || blocked || revision === null) return
    } else if (action !== 'play-unsaved' || revision !== null || status !== 'error') return
    if (inFlight) await inFlight
    if (!permitted() || (action !== 'play-unsaved' && blocked)) return
    confirm = null
    if (!chosen && saved?.state) game.restore(saved.state)
    chosen = true
    acknowledged = ''
    game.start()
    emit()
  }
  const periodic = setInterval(() => {
    if (hasUnsaved() && canWrite()) void flush()
  }, 10_000)
  return {
    initialize,
    command,
    observe,
    flush,
    beforeLeave,
    hasUnsaved,
    view: () => ({
      hasSaved: !!saved?.state,
      confirm,
      status,
      message,
      serverChoice,
      busy: !!inFlight || !!loading || resetting,
      chosen,
      practice,
      menuPage,
      state: game.snapshot(),
      runtimeStatus: game.status(),
      updatedAt: saved?.updated_at ?? null,
    }),
    dispose() {
      if (!alive) return
      alive = false
      listener = null
      clearCheckpoint()
      clearInterval(periodic)
      requests.forEach((controller) => controller.abort())
      requests.clear()
      saved = null
      acknowledged = ''
      revision = null
      chosen = false
      game.deny()
    },
  }
}
export type MoonfallSession = ReturnType<typeof createMoonfallSession>
