import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { getJson, postJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'
import { LibraryFreshnessPanel } from './LibraryFreshnessPanel'

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

test('uses a small 25-game batch by default and requires confirmation for the 500-game request', async () => {
  vi.mocked(getJson).mockResolvedValue([{ uuid: 'lib-1', name: 'PC' }])
  vi.mocked(postJson)
    .mockResolvedValueOnce({
      updated: [{ uuid: 'game-1', name: 'Example', status: 'current' }],
      errors: [],
      skipped_fresh: 2,
    })
    .mockResolvedValueOnce({ updated: [], errors: [], skipped_fresh: 0 })
  vi.mocked(confirmAction).mockResolvedValue(false)

  render(<LibraryFreshnessPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Open update checks' }))
  await screen.findByRole('option', { name: 'PC' })
  expect(screen.getByText(/Store requests can be rate-limited/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText(/Library/), { target: { value: 'lib-1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Refresh batch' }))
  await screen.findByText(/1 updated, 2 skipped as fresh/)
  expect(postJson).toHaveBeenNthCalledWith(1, '/api/admin/freshness/refresh', {
    limit: 25,
    only_stale: true,
    library_uuid: 'lib-1',
  })

  fireEvent.click(screen.getByRole('button', { name: 'Refresh up to 500 games' }))
  await waitFor(() =>
    expect(confirmAction).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Refresh up to 500 games in library PC?',
        confirmLabel: 'Start large refresh',
      }),
    ),
  )
  expect(postJson).toHaveBeenCalledTimes(1)

  vi.mocked(confirmAction).mockResolvedValue(true)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh up to 500 games' }))
  await screen.findByText(/0 updated, 0 skipped as fresh/)
  expect(postJson).toHaveBeenNthCalledWith(2, '/api/admin/freshness/refresh', {
    limit: 500,
    only_stale: true,
    library_uuid: 'lib-1',
    entire_library: true,
  })
})

test('rejects invalid batch sizes without sending a request', async () => {
  vi.mocked(getJson).mockResolvedValue([{ uuid: 'lib-1', name: 'PC' }])
  render(<LibraryFreshnessPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Open update checks' }))
  await screen.findByRole('option', { name: 'PC' })
  fireEvent.change(screen.getByLabelText(/Batch size/), { target: { value: '0' } })
  fireEvent.click(screen.getByRole('button', { name: 'Refresh batch' }))
  expect(
    await screen.findByText('Batch size must be a whole number from 1 to 500.'),
  ).toBeInTheDocument()
  expect(postJson).not.toHaveBeenCalled()
})
