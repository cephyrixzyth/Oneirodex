import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinballRuntime } from './runtime'
import { validateMoonfall } from './model'
import { createMoonfallSession, type MoonfallProgressApi } from './session'
import savedRun from '../../../../../tests/fixtures/moonfall-save-v1.json'

const retained: { dispose(): void }[] = []
afterEach(() => {
  retained.splice(0).forEach((entry) => entry.dispose())
  vi.useRealTimers()
})
const saved = () => ({
  game_id: 'moonfall-pinball' as const,
  revision: 3,
  state: validateMoonfall(savedRun),
  updated_at: null,
})
function setup(overrides: Partial<MoonfallProgressApi> = {}) {
  const runtime = createPinballRuntime((event) => session?.observe(event))
  const game = { ...runtime, deny: () => runtime.dispose() }
  const api = {
    load: vi.fn(async () => saved()),
    save: vi.fn(async (revision: number, state: unknown) => ({
      ...saved(),
      revision: revision + 1,
      state: validateMoonfall(state),
    })),
    reset: vi.fn(async (revision: number) => ({ ...saved(), revision: revision + 1, state: null })),
    ...overrides,
  }
  const changed = vi.fn()
  const session = createMoonfallSession(game, 'member-a', changed, api)
  retained.push(session)
  return { session, runtime, api, changed }
}
const defer = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('identity-bound game session and saves', () => {
  it('offers a saved run without starting it and resumes only on request', async () => {
    const { session, runtime, api } = setup()
    await session.initialize()
    expect(session.view().hasSaved).toBe(true)
    expect(runtime.status()).toBe('idle')
    expect(runtime.snapshot().score).toBe(0)
    expect(api.save).not.toHaveBeenCalled()
    await session.command('resume')
    expect(runtime.status()).toBe('running')
    expect(runtime.snapshot().score).toBe(savedRun.score)
  })

  it('confirms replacing a saved run and preserves its personal best/settings', async () => {
    const { session, runtime, api } = setup()
    await session.initialize()
    await session.command('new')
    expect(session.view().confirm).toBe('new')
    expect(runtime.status()).toBe('idle')
    await session.command('confirm-new')
    expect(runtime.snapshot().score).toBe(0)
    expect(runtime.snapshot().best).toBe(savedRun.best)
    expect(await session.flush()).toBe(true)
    expect(api.save).toHaveBeenCalledWith(
      3,
      expect.objectContaining({ score: 0, best: 500 }),
      expect.any(AbortSignal),
    )
  })

  it('captures the latest paused state before allowing a room exit', async () => {
    const { session, runtime, api } = setup()
    await session.initialize()
    await session.command('resume')
    runtime.tick(1 / 120)
    expect(await session.beforeLeave()).toBe(true)
    expect(runtime.status()).toBe('paused')
    expect(api.save).toHaveBeenCalledWith(
      3,
      expect.objectContaining({ tick: savedRun.tick + 1 }),
      expect.any(AbortSignal),
    )
  })

  it('coalesces in-flight saves without treating a newer run state as already saved', async () => {
    const gate = defer<ReturnType<typeof saved>>()
    let first = true
    const save = vi.fn(async (revision: number, state: unknown) => {
      if (first) {
        first = false
        return gate.promise
      }
      return { ...saved(), revision: revision + 1, state: validateMoonfall(state) }
    })
    const { session, runtime } = setup({ save })
    await session.initialize()
    await session.command('resume')
    runtime.tick(1 / 120)
    const captured = runtime.snapshot()
    const firstSave = session.flush()
    runtime.tick(0.1)
    const coalesced = session.flush()
    expect(save).toHaveBeenCalledTimes(1)
    gate.resolve({ ...saved(), revision: 4, state: captured })
    await Promise.all([firstSave, coalesced])
    expect(session.hasUnsaved()).toBe(true)
    expect(await session.beforeLeave()).toBe(true)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save.mock.calls[1][0]).toBe(4)
  })

  it('keeps network-only play in memory and does not overwrite an unknown server revision', async () => {
    const { session, runtime, api } = setup({
      load: vi.fn(async () => {
        throw new TypeError('network')
      }),
    })
    await session.initialize()
    await session.command('play-unsaved')
    expect(runtime.status()).toBe('running')
    expect(await session.beforeLeave()).toBe(false)
    expect(api.save).not.toHaveBeenCalled()
    expect(session.view().status).toBe('error')
  })

  it('keeps a conflicting local run until the player explicitly chooses the server run', async () => {
    const { session, runtime, api } = setup({
      save: vi.fn(async () => {
        throw Object.assign(new Error('conflict'), { status: 409 })
      }),
    })
    await session.initialize()
    await session.command('new')
    await session.command('confirm-new')
    expect(await session.flush()).toBe(false)
    expect(session.view().status).toBe('conflict')
    expect(runtime.snapshot().score).toBe(0)
    await session.command('retry')
    expect(runtime.snapshot().score).toBe(0)
    expect(session.view().serverChoice).toBe(true)
    expect(api.save).toHaveBeenCalledTimes(1)
    await session.command('load-server')
    expect(runtime.snapshot().score).toBe(500)
    expect(runtime.status()).toBe('paused')
  })

  it('clears private state and stops the runtime on access denial', async () => {
    const { session, runtime } = setup({
      save: vi.fn(async () => {
        throw Object.assign(new Error('denied'), { status: 403 })
      }),
    })
    await session.initialize()
    await session.command('resume')
    runtime.tick(1 / 120)
    expect(await session.flush()).toBe(false)
    expect(session.view().status).toBe('denied')
    expect(session.view().hasSaved).toBe(false)
    expect(runtime.status()).toBe('disposed')
    expect(runtime.snapshot().best).toBe(0)
    expect(await session.beforeLeave()).toBe(true)
  })

  it('ignores a late response after disposal and aborts its owned request', async () => {
    const gate = defer<ReturnType<typeof saved>>()
    let signal: AbortSignal | undefined
    const { session, runtime, changed } = setup({
      load: async (value) => {
        signal = value
        return gate.promise
      },
    })
    const pending = session.initialize()
    session.dispose()
    const count = changed.mock.calls.length
    expect(signal?.aborted).toBe(true)
    gate.resolve(saved())
    await pending
    expect(changed).toHaveBeenCalledTimes(count)
    expect(runtime.snapshot().best).toBe(0)
  })

  it('requires reset confirmation and retains the returned empty revision', async () => {
    const { session, runtime, api } = setup()
    await session.initialize()
    await session.command('reset')
    expect(api.reset).not.toHaveBeenCalled()
    expect(session.view().confirm).toBe('reset')
    await session.command('confirm-reset')
    expect(api.reset).toHaveBeenCalledWith(3, expect.any(AbortSignal))
    expect(session.view().hasSaved).toBe(false)
    expect(runtime.snapshot().best).toBe(0)
    await session.command('new')
    await session.flush()
    expect(api.save).toHaveBeenCalledWith(4, expect.any(Object), expect.any(AbortSignal))
  })
})

it('lets an offline run resume after focus loss without writing an unknown revision', async () => {
  const { session, runtime, api } = setup({
    load: vi.fn(async () => {
      throw new TypeError('offline')
    }),
  })
  await session.initialize()
  await session.command('play-unsaved')
  runtime.pause()
  await session.command('continue-unsaved')
  expect(runtime.status()).toBe('running')
  expect(api.save).not.toHaveBeenCalled()
  expect(session.view().status).toBe('error')
})

it('does not allow memory-only play to race a pending retry read', async () => {
  const gate = defer<ReturnType<typeof saved>>()
  let attempt = 0
  const { session, runtime, api } = setup({
    load: async () => {
      if (!attempt++) throw new TypeError('offline')
      return gate.promise
    },
  })
  await session.initialize()
  const pending = session.command('retry')
  expect(session.view().busy).toBe(true)
  await session.command('play-unsaved')
  gate.resolve(saved())
  await pending
  expect(runtime.status()).toBe('idle')
  expect(api.save).not.toHaveBeenCalled()
})
it('cannot resume through a replacement confirmation', async () => {
  const { session, runtime } = setup()
  await session.initialize()
  await session.command('resume')
  await session.command('new')
  await session.command('resume')
  expect(runtime.status()).toBe('paused')
})

it('keeps guided practice separate from the saved run and personal best', async () => {
  const { session, runtime, api } = setup()
  await session.initialize()
  await session.command('practice')
  expect(runtime.status()).toBe('running')
  expect(session.view().practice).toBe(true)
  expect(runtime.snapshot().best).toBe(0)
  runtime.tick(0.1)
  expect(await session.flush()).toBe(true)
  expect(api.save).not.toHaveBeenCalled()
  await session.command('finish-practice')
  expect(session.view().hasSaved).toBe(true)
  await session.command('resume')
  expect(runtime.snapshot().score).toBe(500)
})

it('exposes headset comfort and recovery actions through the same guarded session', async () => {
  const { session, runtime } = setup()
  await session.initialize()
  await session.command('resume')
  await session.command('options')
  expect(session.view().menuPage).toBe('comfort')
  await session.command('quality')
  expect(runtime.snapshot().settings.quality).toBe('high')
  await session.command('back')
  expect(session.view().menuPage).toBe('main')
  await session.command('resume')
  await session.command('recover')
  runtime.tick(1 / 120)
  expect(runtime.snapshot().recoveries).toBe(1)
})
