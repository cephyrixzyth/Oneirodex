import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getJson } from '../api/adminApi'
import { StatisticsPage } from './StatisticsPage'

vi.mock('../api/adminApi', () => ({ getJson: vi.fn() }))
const stats = {
  totals: { games: 4, libraries: 2, users: 3, downloads: 8, favorites: 5, library_bytes: 2048 },
  top_games_table: [{ name: 'Example title', downloads: 6 }],
  downloads_per_user: { labels: ['Mina'], data: [3] },
  top_games: { labels: ['Example title'], data: [6] },
  download_trends: { labels: ['2026-10-12'], data: [2] },
  users_with_invites: { labels: ['Mina'], data: [4] },
  top_downloaders: { labels: ['Mina'], data: [3] },
  top_collectors: { labels: ['Mina'], data: [5] },
}
describe('StatisticsPage', () => {
  beforeEach(() => vi.clearAllMocks())
  it('renders totals, all existing statistic groups and the exact top-title table', async () => {
    vi.mocked(getJson).mockResolvedValue(stats)
    render(<StatisticsPage />)
    expect(await screen.findByText('2.0 KB')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Download trends (30 days)' })).toHaveTextContent(
      '2026-10-12',
    )
    expect(screen.getByRole('table', { name: 'Most downloaded titles' })).toHaveTextContent(
      'Example title',
    )
    expect(screen.getByRole('region', { name: 'Top game collectors' })).toHaveTextContent('5')
  })
  it('offers Retry after a failed request', async () => {
    vi.mocked(getJson).mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce(stats)
    render(<StatisticsPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry loading statistics' }))
    await waitFor(() => expect(getJson).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('region', { name: 'Library totals' })).toBeInTheDocument()
  })
})
