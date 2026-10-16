import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { getJson, postJson } from '../api/adminApi'
import { LibraryProposalsPanel } from './LibraryProposalsPanel'
import { confirmAction } from '@oneirodex/ui'

vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@oneirodex/ui')>()
  return { ...actual, confirmAction: vi.fn() }
})

test('loads suggestions only when opened and renders the existing read-only proposal data', async () => {
  vi.mocked(getJson).mockResolvedValue({
    proposals: [
      {
        game_uuid: 'game-1',
        game_name: 'Example Game',
        library_name: 'PC',
        path: '/storage/games/example',
        proposal: {
          guessed_name: 'Example',
          candidates: [{ igdb_id: 123, name: 'Example Candidate', score: 0.91 }],
        },
      },
    ],
  })
  render(<LibraryProposalsPanel />)
  expect(getJson).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Review suggested fixes' }))
  await screen.findByRole('button', { name: 'Approve Example Candidate (0.91)' })
  expect(getJson).toHaveBeenCalledWith(
    '/api/library_tools/proposals',
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  )
  expect(screen.getByRole('region', { name: 'Suggested fixes' })).toBeTruthy()
})

test('shows an empty state and supports a bounded retry after an API error', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Unavailable'))
    .mockResolvedValueOnce({ proposals: [] })
  render(<LibraryProposalsPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Review suggested fixes' }))
  expect(await screen.findByText('Unable to load suggestions.')).toBeInTheDocument()
  const callsBeforeRetry = vi.mocked(getJson).mock.calls.length
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() =>
    expect(screen.getByText('No suggested fixes were found.')).toBeInTheDocument(),
  )
  expect(getJson).toHaveBeenCalledTimes(callsBeforeRetry + 1)
})

test('requires confirmation before clearing a proposal and links approved matches to identify', async () => {
  vi.mocked(getJson)
    .mockResolvedValueOnce({
      proposals: [
        {
          game_uuid: 'game-1',
          library_uuid: 'lib-1',
          game_name: 'Example Game',
          path: '/storage/games/Example & More',
          proposal: { candidates: [{ igdb_id: 123, name: 'Example Candidate', score: 0.91 }] },
        },
      ],
    })
    .mockResolvedValueOnce({ proposals: [] })
  vi.mocked(confirmAction).mockResolvedValue(false)
  render(<LibraryProposalsPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Review suggested fixes' }))
  const approve = await screen.findByRole('button', { name: 'Approve Example Candidate (0.91)' })
  fireEvent.click(approve)
  await waitFor(() => expect(confirmAction).toHaveBeenCalled())
  expect(postJson).not.toHaveBeenCalled()

  vi.mocked(confirmAction).mockResolvedValue(true)
  vi.mocked(postJson).mockResolvedValue({ identify_hint: '/add_game_manual' })
  fireEvent.click(approve)
  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/library_tools/proposals/approve', {
      path: '/storage/games/Example & More',
      igdb_id: 123,
    }),
  )
  const handoff = await screen.findByRole('link', { name: 'Continue identify' })
  expect(handoff).toHaveAttribute(
    'href',
    '/add_game_manual?full_disk_path=%2Fstorage%2Fgames%2FExample+%26+More&igdb_id=123&library_uuid=lib-1',
  )
})
