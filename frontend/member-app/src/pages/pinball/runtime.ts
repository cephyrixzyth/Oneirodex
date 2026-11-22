import { newMoonfall, stepMoonfall, validateMoonfall } from './model'
import type { MoonfallInput, MoonfallSettings, MoonfallState } from './model'
import { FIXED_STEP } from './table'

export type MoonfallStatus = 'idle' | 'running' | 'paused' | 'result' | 'disposed'
export interface MoonfallSnapshot {
  state: MoonfallState
  status: MoonfallStatus
  reason: 'start' | 'restore' | 'pause' | 'resume' | 'tick' | 'transition' | 'result' | 'settings'
}

/** Simulation lifecycle only. Scene owns the frame clock; UI owns persistence. */
export function createPinballRuntime(onSnapshot: (snapshot: MoonfallSnapshot) => void = () => {}) {
  let state = newMoonfall()
  let status: MoonfallStatus = 'idle'
  let accumulator = 0
  let lastSnapshotTick = 0
  let listener: typeof onSnapshot | null = onSnapshot
  const held: MoonfallInput = { left: false, right: false, launch: false, recover: false }
  const pulse = { launch: false, recover: false }
  const sources = new Map<string, MoonfallInput>()
  const copy = () => JSON.parse(JSON.stringify(state)) as MoonfallState
  function emit(reason: MoonfallSnapshot['reason']) {
    lastSnapshotTick = state.tick
    listener?.({ state: copy(), status, reason })
  }
  function releaseAll() {
    sources.clear()
    held.left = held.right = held.launch = held.recover = false
    pulse.launch = pulse.recover = false
    accumulator = 0
  }
  function input(action: keyof MoonfallInput, pressed: boolean, source = 'primary') {
    if (status !== 'running') return
    const previous = held[action]
    const values = sources.get(source) || {
      left: false,
      right: false,
      launch: false,
      recover: false,
    }
    values[action] = pressed
    if (Object.values(values).some(Boolean)) sources.set(source, values)
    else sources.delete(source)
    held[action] = [...sources.values()].some((value) => value[action])
    if ((action === 'launch' || action === 'recover') && held[action] && !previous)
      pulse[action] = true
    if (!held[action] && action === 'launch') state.lastLaunch = false
    if (!held[action] && action === 'recover') state.lastRecover = false
  }
  return {
    status: () => status,
    snapshot: copy,
    readState: (): Readonly<MoonfallState> => state,
    start() {
      if (status === 'disposed') return
      const best = state.best
      const settings = { ...state.settings }
      state = newMoonfall()
      state.best = best
      state.settings = settings
      releaseAll()
      status = 'running'
      emit('start')
    },
    restore(value: unknown) {
      if (status === 'disposed') return
      const restored = validateMoonfall(value)
      releaseAll()
      state = restored
      status = 'paused'
      emit('restore')
    },
    setSettings(value: Partial<MoonfallSettings>) {
      if (status === 'disposed') return
      state = validateMoonfall({ ...state, settings: { ...state.settings, ...value } })
      emit('settings')
    },
    input,
    releaseSource(source: string) {
      for (const action of ['left', 'right', 'launch', 'recover'] as const)
        input(action, false, source)
    },
    pause() {
      if (status !== 'running') return
      releaseAll()
      status = 'paused'
      emit('pause')
    },
    resume() {
      if (status !== 'paused') return
      releaseAll()
      status = state.phase === 'complete' || state.phase === 'game-over' ? 'result' : 'running'
      emit(status === 'result' ? 'result' : 'resume')
    },
    tick(seconds: number) {
      if (status !== 'running' || !Number.isFinite(seconds) || seconds <= 0) return
      accumulator = Math.min(0.1, accumulator + Math.min(0.1, seconds))
      const previousPhase = state.phase
      let steps = 0
      while (accumulator + 1e-10 >= FIXED_STEP && steps < 12) {
        stepMoonfall(
          state,
          { ...held, launch: held.launch || pulse.launch, recover: held.recover || pulse.recover },
          FIXED_STEP,
        )
        pulse.launch = pulse.recover = false
        accumulator = Math.max(0, accumulator - FIXED_STEP)
        steps++
        if (state.phase === 'complete' || state.phase === 'game-over') {
          releaseAll()
          status = 'result'
          emit('result')
          return
        }
      }
      if (state.phase !== previousPhase) emit('transition')
      else if (state.tick - lastSnapshotTick >= 30) emit('tick')
    },
    dispose() {
      if (status === 'disposed') return
      listener = null
      releaseAll()
      state = newMoonfall()
      status = 'disposed'
    },
  }
}

export type PinballRuntime = ReturnType<typeof createPinballRuntime>
