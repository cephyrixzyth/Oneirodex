import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DownloadsPage } from './DownloadsPage'
import { getJson, deleteJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'

vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), deleteJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (original) => ({ ...(await original()), confirmAction: vi.fn() }))
const row = {
  id: 7,
  username: 'Mina',
  game_uuid: '12345678',
  status: 'pending',
  file_name: 'bundle.zip',
  request_time: '2026-10-12T10:00:00Z',
  completion_time: null,
}
describe('DownloadsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  it('shows the named requests table and reports an empty collection', async () => {
    vi.mocked(getJson).mockResolvedValue({ requests: [row] })
    render(<DownloadsPage />)
    const table = await screen.findByRole('table', { name: 'Download requests' })
    expect(within(table).getByText('Mina')).toBeInTheDocument()
    expect(within(table).getByText('bundle.zip')).toBeInTheDocument()
    expect(
      within(table).getByRole('button', { name: 'Delete download request 7' }),
    ).toBeInTheDocument()
  })
  it('requires confirmation before deletion and removes the row after success', async () => {
    vi.mocked(getJson).mockResolvedValue({ requests: [row] })
    vi.mocked(confirmAction).mockResolvedValueOnce(false).mockResolvedValueOnce(true)
    vi.mocked(deleteJson).mockResolvedValue({ ok: true })
    render(<DownloadsPage />)
    const remove = await screen.findByRole('button', { name: 'Delete download request 7' })
    fireEvent.click(remove)
    await waitFor(() => expect(confirmAction).toHaveBeenCalledTimes(1))
    expect(deleteJson).not.toHaveBeenCalled()
    fireEvent.click(remove)
    await waitFor(() => expect(deleteJson).toHaveBeenCalledWith('/api/delete_download/7'))
    expect(await screen.findByText('No download requests found.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Download request 7 deleted.')
  })
  it('offers Retry after a malformed or failed load', async () => {
    vi.mocked(getJson)
      .mockRejectedValueOnce(new Error('Offline'))
      .mockResolvedValueOnce({ requests: [] })
    render(<DownloadsPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry loading download requests' }))
    await waitFor(() => expect(getJson).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('No download requests found.')).toBeInTheDocument()
  })
})
