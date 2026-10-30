import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { getJson, postJsonResult } from '../api/adminApi'
import { DeleteLibrariesModal } from './DeleteLibrariesModal'

vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  postJsonResult: vi.fn(),
}))

vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))

const eventSources: FakeEventSource[] = []

class FakeEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  close = vi.fn()

  constructor() {
    eventSources.push(this)
  }
}

test('shows the game currently being deleted in the progress announcement', async () => {
  eventSources.length = 0
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.mocked(getJson).mockReset()
  vi.mocked(getJson).mockResolvedValue({
    status: 'deleting_games',
    message: 'Deleting game 1/1',
  })
  vi.mocked(postJsonResult).mockResolvedValue({
    ok: true,
    data: { jobs: [{ job_id: 'delete-job-1' }] },
  } as Awaited<ReturnType<typeof postJsonResult>>)

  render(
    <DeleteLibrariesModal
      targets={[{ uuid: 'library-1', name: 'Synthetic Library' }]}
      onClose={vi.fn()}
      onDeleted={vi.fn()}
    />,
  )

  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: 'Synthetic Library' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))

  await waitFor(() => expect(eventSources).toHaveLength(1))
  await act(async () => {
    eventSources[0].onmessage?.({
      data: JSON.stringify({
        status: 'deleting_games',
        message: 'Deleting game 1/1',
        current_game: 'Example Game',
        current: 0,
        total: 1,
      }),
    } as MessageEvent)
  })

  expect(await screen.findByText('Deleting game 1/1')).toBeInTheDocument()
  expect(screen.getByText('Example Game')).toBeInTheDocument()
  expect(getJson).toHaveBeenCalledWith('/check_deletion_progress/delete-job-1')
})

test('polls completion while the EventSource sends no progress events', async () => {
  eventSources.length = 0
  vi.mocked(getJson).mockReset()
  vi.mocked(postJsonResult).mockReset()
  vi.stubGlobal('EventSource', FakeEventSource)
  const onDeleted = vi.fn()
  vi.mocked(postJsonResult).mockResolvedValue({
    ok: true,
    data: { jobs: [{ job_id: 'delete-job-stalled-sse' }] },
  } as Awaited<ReturnType<typeof postJsonResult>>)
  vi.mocked(getJson).mockResolvedValue({
    status: 'completed',
    message: 'Library deleted successfully.',
  })

  try {
    render(
      <DeleteLibrariesModal
        targets={[{ uuid: 'library-1', name: 'Synthetic Library' }]}
        onClose={vi.fn()}
        onDeleted={onDeleted}
      />,
    )
    await act(async () => {
      fireEvent.change(screen.getByRole('textbox'), {
        target: { value: 'Synthetic Library' },
      })
      fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))
      await Promise.resolve()
    })
    expect(eventSources).toHaveLength(1)

    await waitFor(() =>
      expect(getJson).toHaveBeenCalledWith('/check_deletion_progress/delete-job-stalled-sse'),
    )
    expect(onDeleted).toHaveBeenCalledOnce()
    expect(eventSources[0].close).toHaveBeenCalled()
  } finally {
    vi.unstubAllGlobals()
  }
})
