import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { OpsApp } from './OpsApp'
import { fetchOpsSummary } from './api/summary'

vi.mock('./api/summary', () => ({
  fetchOpsSummary: vi.fn(),
}))

const snapshot = {
  as_of: '2026-07-22T23:00:00+00:00',
  host: {
    hostname: 'ops-host',
    os: 'Linux',
    ip: '127.0.0.1',
    python: '3.12',
    cpu: { percent: 10, cores_physical: 4, cores_logical: 8 },
    memory: { total: 1000, used: 500, available: 500, percent: 50 },
    disk_base: { total: 1000, used: 500, free: 500, percent: 50 },
    disk_games: { total: 1000, used: 500, free: 500, percent: 50 },
    uptime_system: '1 day',
    uptime_app: '1 hour',
  },
  issues: { overall: 'good', items: [] },
}

describe('OpsApp', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  test('renders the hostname from the first successful summary', async () => {
    vi.mocked(fetchOpsSummary).mockResolvedValueOnce(snapshot)

    render(<OpsApp pollMs={15000} />)

    expect(screen.getByRole('heading', { level: 1, name: 'Operations glance' })).toBeInTheDocument()
    expect(await screen.findByText('ops-host')).toBeInTheDocument()
  })

  test('announces initial and changed severity without repeating unchanged polls', async () => {
    vi.mocked(fetchOpsSummary)
      .mockResolvedValueOnce(snapshot)
      .mockResolvedValueOnce({
        ...snapshot,
        as_of: '2026-07-22T23:00:15+00:00',
      })
      .mockResolvedValueOnce({
        ...snapshot,
        as_of: '2026-07-22T23:00:30+00:00',
        issues: { overall: 'warn', items: [] },
      })
    const user = userEvent.setup()

    render(<OpsApp pollMs={15000} />)

    expect(await screen.findByText('ops-host')).toBeInTheDocument()
    const status = screen.getByRole('status')
    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(status).toHaveAttribute('aria-atomic', 'true')
    expect(status).toHaveTextContent('All systems healthy')

    await user.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(screen.getByText(/Updated/)).toBeInTheDocument())
    expect(status).toHaveTextContent('All systems healthy')

    await user.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(status).toHaveTextContent('Attention needed'))
  })

  test('aborts an in-flight request on unmount without applying its result', async () => {
    let resolveSummary: (value: any) => void = () => {}
    vi.mocked(fetchOpsSummary).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSummary = resolve
        }),
    )

    const { unmount } = render(<OpsApp pollMs={15000} />)
    const signal = vi.mocked(fetchOpsSummary).mock.calls[0][0]!.signal

    unmount()
    resolveSummary(snapshot)

    await waitFor(() => expect(signal!.aborted).toBe(true))
    expect(screen.queryByText('ops-host')).not.toBeInTheDocument()
  })

  test('announces the first load as a polite status', () => {
    vi.mocked(fetchOpsSummary).mockImplementationOnce(() => new Promise(() => {}))

    render(<OpsApp pollMs={15000} />)

    // Shared PageStatus (wave B1.2) animates the trailing ellipsis, so the
    // status reads "Loading operations summary" + " ." / " .." / " ..." — the
    // same treatment the admin SPA already gave it.
    const status = screen.getByRole('status')
    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(status).toHaveTextContent(/Loading operations summary\s*\.{1,3}/)
    expect(screen.queryByText('Host data unavailable.')).not.toBeInTheDocument()
  })

  test('first failed load uses the shared error status instead of empty panels', async () => {
    vi.mocked(fetchOpsSummary).mockRejectedValueOnce(new Error('offline'))

    render(<OpsApp pollMs={15000} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.queryByText('Host data unavailable.')).not.toBeInTheDocument()
    expect(screen.queryByText('ops-host')).not.toBeInTheDocument()
  })

  test('keeps the previous snapshot and offers Retry after a failed refresh', async () => {
    vi.mocked(fetchOpsSummary)
      .mockResolvedValueOnce(snapshot)
      .mockRejectedValueOnce(new Error('offline'))
    const user = userEvent.setup()

    render(<OpsApp pollMs={15000} />)
    expect(await screen.findByText('ops-host')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Refresh' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.getByText('ops-host')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
