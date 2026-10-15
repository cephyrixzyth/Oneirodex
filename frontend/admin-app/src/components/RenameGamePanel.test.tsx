import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { getJson, postJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'
import { RenameGamePanel } from './RenameGamePanel'

vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@oneirodex/ui')>()
  return { ...actual, confirmAction: vi.fn() }
})

beforeEach(() => {
  vi.mocked(getJson).mockReset()
  vi.mocked(postJson).mockReset()
  vi.mocked(confirmAction).mockReset()
})

test('searches, previews selected path operations, and confirms only checked renames', async () => {
  vi.mocked(getJson).mockResolvedValue([
    { uuid: 'game-1', name: 'Demo Game', full_disk_path: '/storage/games/Demo Game' },
  ])
  vi.mocked(postJson)
    .mockResolvedValueOnce({
      plan: [
        {
          kind: 'root_folder',
          from_path: '/storage/games/Demo Game',
          to_path: '/storage/games/Demo Game (2020)',
        },
        {
          kind: 'top_level_media',
          from_path: '/storage/games/Demo Game/cover.jpg',
          to_path: '/storage/games/Demo Game (2020)/Demo Game (2020).jpg',
        },
      ],
    })
    .mockResolvedValueOnce({ results: [{ ok: true }, { ok: true }] })
  vi.mocked(confirmAction).mockResolvedValue(true)

  render(<RenameGamePanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Open rename tools' }))
  fireEvent.change(screen.getByLabelText('Find game'), { target: { value: 'Demo' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search games' }))
  fireEvent.click(await screen.findByRole('button', { name: /Demo Game/ }))
  fireEvent.change(screen.getByLabelText('Year (optional)'), { target: { value: '2020' } })
  fireEvent.click(screen.getByRole('button', { name: 'Preview rename' }))
  await screen.findByRole('table', { name: 'Rename preview' })
  expect(postJson).toHaveBeenCalledWith(
    '/api/library_tools/rename/preview',
    expect.objectContaining({
      game_uuid: 'game-1',
      year: '2020',
      rename_root: true,
    }),
  )

  fireEvent.click(screen.getByRole('button', { name: 'Apply selected renames' }))
  await waitFor(() =>
    expect(confirmAction).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Apply 2 rename operations?',
        tone: 'danger',
        confirmLabel: 'Apply selected renames',
      }),
    ),
  )
  await screen.findByText(/Rename complete: 2 succeeded/)
  expect(postJson).toHaveBeenLastCalledWith('/api/library_tools/rename/apply', {
    game_uuid: 'game-1',
    plan: [
      {
        kind: 'root_folder',
        from_path: '/storage/games/Demo Game',
        to_path: '/storage/games/Demo Game (2020)',
      },
      {
        kind: 'top_level_media',
        from_path: '/storage/games/Demo Game/cover.jpg',
        to_path: '/storage/games/Demo Game (2020)/Demo Game (2020).jpg',
      },
    ],
  })
})

test('does not apply operations when the shared confirmation is canceled', async () => {
  vi.mocked(getJson).mockResolvedValue([{ uuid: 'game-2', name: 'Other Game' }])
  vi.mocked(postJson).mockResolvedValueOnce({
    plan: [{ kind: 'root_folder', from_path: '/storage/Other', to_path: '/storage/Other 2' }],
  })
  vi.mocked(confirmAction).mockResolvedValue(false)
  render(<RenameGamePanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Open rename tools' }))
  fireEvent.change(screen.getByLabelText('Find game'), { target: { value: 'Other' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search games' }))
  fireEvent.click(await screen.findByRole('button', { name: /Other Game/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Preview rename' }))
  await screen.findByRole('table', { name: 'Rename preview' })
  fireEvent.click(screen.getByRole('button', { name: 'Apply selected renames' }))
  await waitFor(() => expect(confirmAction).toHaveBeenCalled())
  expect(postJson).toHaveBeenCalledTimes(1)
})
