import { act, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { LibraryRoom } from './LibraryRoom'
import { createPinballRuntime } from './pinball/runtime'
import type { MoonfallSnapshot } from './pinball/runtime'
import savedRun from '../../../../tests/fixtures/moonfall-save-v1.json'
import { validateMoonfall } from './pinball/model'
const progress = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), reset: vi.fn() }))
vi.mock('./pinball/progress', () => ({
  loadMoonfallProgress: progress.load,
  saveMoonfallProgress: progress.save,
  resetMoonfallProgress: progress.reset,
}))
let emit: ((value: MoonfallSnapshot) => void) | undefined
let runtime: ReturnType<typeof createPinballRuntime>
vi.mock('./roomScene', () => ({
  createRoom: (
    _: unknown,
    select: (id: string) => void,
    _xr: unknown,
    _error: unknown,
    options: { onGameSnapshot: typeof emit },
  ) => {
    emit = options.onGameSnapshot
    runtime = createPinballRuntime((value) => emit?.(value))
    return {
      game: { ...runtime, deny: () => runtime.dispose() },
      update: vi.fn(),
      move: vi.fn(),
      setGameMenu: vi.fn(),
      dispose: () => runtime.dispose(),
    }
  },
}))
test('owns the game session and requires explicit resume before play', async () => {
  progress.load.mockResolvedValue({
    game_id: 'moonfall-pinball',
    revision: 3,
    state: validateMoonfall(savedRun),
    updated_at: null,
  })
  progress.save.mockImplementation(async (revision, state) => ({
    game_id: 'moonfall-pinball',
    revision: revision + 1,
    state,
    updated_at: null,
  }))
  const user = userEvent.setup()
  const select = vi.fn()
  const { unmount } = render(
    <LibraryRoom
      memberId="member-a"
      initiallyOpen
      scope=""
      onScope={vi.fn()}
      onFavorites={vi.fn()}
      games={[]}
      page={1}
      pages={1}
      pageSize={48}
      total={0}
      ready
      error={false}
      selected={null}
      detailMessage=""
      onSelect={select}
      onPage={vi.fn()}
      onFavorite={vi.fn()}
      favoriteMessage=""
    />,
  )
  await user.click(await screen.findByRole('button', { name: 'Resume saved run' }))
  expect(runtime.status()).toBe('running')
  act(() => runtime.tick(1 / 120))
  await user.click(screen.getByRole('button', { name: 'Close room' }))
  expect(progress.save).toHaveBeenCalledWith(
    3,
    expect.objectContaining({ tick: 1501 }),
    expect.any(AbortSignal),
  )
  expect(runtime.status()).toBe('disposed')
  expect(select).not.toHaveBeenCalled()
  unmount()
})

test('honors the latest world choice while an exit save is pending', async () => {
  progress.load.mockResolvedValue({
    game_id: 'moonfall-pinball',
    revision: 3,
    state: validateMoonfall(savedRun),
    updated_at: null,
  })
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  progress.save.mockImplementation(async (revision, state) => {
    await gate
    return { game_id: 'moonfall-pinball', revision: revision + 1, state, updated_at: null }
  })
  const user = userEvent.setup()
  const { unmount } = render(
    <LibraryRoom
      memberId="member-a"
      initiallyOpen
      scope=""
      onScope={vi.fn()}
      onFavorites={vi.fn()}
      games={[]}
      page={1}
      pages={1}
      pageSize={48}
      total={0}
      ready
      error={false}
      selected={null}
      detailMessage=""
      onSelect={vi.fn()}
      onPage={vi.fn()}
      onFavorite={vi.fn()}
      favoriteMessage=""
    />,
  )
  await user.click(await screen.findByRole('button', { name: 'Resume saved run' }))
  act(() => runtime.tick(1 / 120))
  await user.selectOptions(screen.getByLabelText('Visit room'), 'greenhouse')
  await user.selectOptions(screen.getByLabelText('Visit room'), 'oneirodex')
  const pendingChoice = (screen.getByLabelText('Visit room') as HTMLSelectElement).value
  release()
  await waitFor(() => expect(screen.getByLabelText('Visit room')).toHaveValue('oneirodex'))
  unmount()
  expect(pendingChoice).toBe('oneirodex')
})
