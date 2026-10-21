import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { confirmAction } from '@oneirodex/ui'
import { LibrariesPage } from './LibrariesPage'
import { ScansPage } from './ScansPage'
import { SCAN_QUEUE_POLICY } from '../components/scanQueuePolicy'

vi.mock('@oneirodex/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@oneirodex/ui')>()
  return { ...actual, confirmAction: vi.fn() }
})

describe('ScansPage queued jobs', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        if (String(url).includes('/api/scan_jobs_status')) {
          return {
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),

            text: async function () {
              return JSON.stringify(await this.json())
            },
            json: async () => [
              {
                id: 'aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb',
                library_name: 'PCWIN',
                status: 'Running',
                scan_folder: '/storage/pc',
                folders_success: 1,
                folders_failed: 0,
                total_folders: 10,
              },
              {
                id: 'cccccccc-4444-5555-6666-dddddddddddd',
                library_name: 'PS2',
                status: 'Queued',
                queue_position: 1,
                scan_folder: '/storage/ps2',
              },
            ],
          }
        }
        return {
          ok: false,
          status: 404,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({}),
        }
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.mocked(confirmAction).mockReset()
  })

  test('lists Running and Queued jobs from scan_jobs_status array', async () => {
    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    // Was `/Running: yes/` + `/queued 1/` — the developer readout GT-B34
    // replaced. The summary now names the library and its progress.
    expect(await screen.findByText(/Scanning PCWIN/i)).toBeInTheDocument()
    expect(screen.getByText(/Scanning PCWIN — 1\/10/i)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText(/Queued \(#1\)/)).toBeInTheDocument()
    })
    expect(screen.getByText(/\(#1\)/)).toBeInTheDocument()
    expect(screen.getByText('PCWIN')).toBeInTheDocument()
    expect(screen.getByText('PS2')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/Scanning/i)
    expect(screen.getByRole('region', { name: 'Scan jobs table' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel queue' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Dupe glance' })).not.toBeInTheDocument()
  })

  test('cancels a queued scan and refreshes the job list', async () => {
    const user = userEvent.setup()
    let jobs = [
      {
        id: 'queued-job-1',
        library_name: 'PS2',
        status: 'Queued',
        queue_position: 1,
        scan_folder: '/storage/ps2',
      },
    ]
    const fetchMock = vi.fn(async (url) => {
      if (String(url).includes('/api/scan_jobs_status')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          text: async () => JSON.stringify(jobs),
          json: async () => jobs,
        }
      }
      if (String(url) === '/cancel_scan_job/queued-job-1') {
        jobs = [{ ...jobs[0], status: 'Cancelled' }]
        return {
          ok: true,
          status: 200,
          redirected: true,
          url: 'http://localhost/scan_management',
          headers: new Headers({ 'content-type': 'text/html' }),
        }
      }
      return {
        ok: false,
        status: 404,
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => '{}',
        json: async () => ({}),
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: 'Cancel queue' }))
    expect(await screen.findByText(/Queued scan job queued-job-1 cancelled/i)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/cancel_scan_job/queued-job-1',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(await screen.findByText('Cancelled')).toBeInTheDocument()
  })

  test('labels a cancelled running job as stopping while it waits for its worker', async () => {
    const jobs = [
      {
        id: 'stopping-1',
        library_name: 'PCWIN',
        status: 'Stopping',
        scan_folder: '/storage/pc',
        folders_success: 1,
        folders_failed: 0,
        total_folders: 10,
      },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => JSON.stringify(jobs),
        json: async () => jobs,
      })),
    )

    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Stopping PCWIN — 1/10')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Stopping…')
    expect(screen.queryByText('Scanning…')).not.toBeInTheDocument()
  })

  test('a queue with nothing running does not read as idle', async () => {
    // The bug this wording exists for: an orphaned Running job held the queue,
    // and the old readout rendered it as "Running: no · queued 1" — which reads
    // as "nothing to do" rather than "stuck". See the scan-ownership fix.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        if (String(url).includes('/api/scan_jobs_status')) {
          return {
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),

            text: async function () {
              return JSON.stringify(await this.json())
            },
            json: async () => [
              { id: 'q1', library_name: 'PS2', status: 'Queued', queue_position: 1 },
            ],
          }
        }
        return {
          ok: false,
          status: 404,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({}),
        }
      }),
    )

    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    const summary = await screen.findByText(/1 scan queued, none running/i)
    expect(summary).toBeInTheDocument()
    expect(summary).toHaveTextContent(/waiting on a job that has not reported a result/i)
  })

  test('a failed job shows why, not just that it failed', async () => {
    // The reason is the only thing that explains a queue that stopped moving,
    // and the table used to drop it entirely even though the API returns it.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        if (String(url).includes('/api/scan_jobs_status')) {
          return {
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),

            text: async function () {
              return JSON.stringify(await this.json())
            },
            json: async () => [
              {
                id: 'f1',
                library_name: 'PCWIN',
                status: 'Failed',
                error_message:
                  'Scan owner process is no longer running; reclaimed so queued scans can start.',
                folders_success: 2,
                folders_failed: 1,
                total_folders: 9,
              },
            ],
          }
        }
        return {
          ok: false,
          status: 404,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({}),
        }
      }),
    )

    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/owner process is no longer running/i)).toBeInTheDocument()
    // …and the progress it got to before dying, which was also never shown.
    expect(screen.getByText('3/9 · 1 failed')).toBeInTheDocument()
  })

  test('keeps full scan history available and filters it by status', async () => {
    const user = userEvent.setup()
    const jobs = Array.from({ length: 13 }, (_, index) => ({
      id: `completed-${index}`,
      library_name: `History ${index}`,
      status: 'Completed',
      scan_folder: `/storage/history-${index}`,
      total_folders: 1,
      folders_success: 1,
    }))
    jobs.push({
      id: 'failed-1',
      library_name: 'Failed history',
      status: 'Failed',
      scan_folder: '/storage/failed',
      total_folders: 1,
      folders_success: 0,
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => JSON.stringify(jobs),
        json: async () => jobs,
      })),
    )

    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('History 12')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Failed (1)' }))
    expect(await screen.findByText('Failed history')).toBeInTheDocument()
    expect(screen.queryByText('History 12')).not.toBeInTheDocument()
  })

  test('exports only the rows in the active scan-job filter', async () => {
    const user = userEvent.setup()
    const jobs = [
      {
        id: 'done-1',
        library_name: 'Completed history',
        status: 'Completed',
        scan_folder: '/storage/done',
        total_folders: 2,
        folders_success: 2,
      },
      {
        id: 'failed-1',
        library_name: 'Failed "history"',
        status: 'Failed',
        last_run: null,
        scan_folder: '/storage/failed',
        total_folders: 2,
        folders_failed: 1,
        error_message: 'Network unavailable',
      },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => JSON.stringify(jobs),
        json: async () => jobs,
      })),
    )
    const blobParts: BlobPart[][] = []
    const NativeBlob = globalThis.Blob
    class CapturedBlob extends NativeBlob {
      constructor(parts?: BlobPart[], options?: BlobPropertyBag) {
        blobParts.push(parts || [])
        super(parts, options)
      }
    }
    vi.stubGlobal('Blob', CapturedBlob)
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:scan-jobs-test')
    const originalDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    try {
      render(
        <MemoryRouter>
          <ScansPage />
        </MemoryRouter>,
      )

      expect(await screen.findByText('Failed "history"')).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'Failed (1)' }))
      await user.click(screen.getByRole('button', { name: 'Export CSV' }))

      expect(createObjectURL).toHaveBeenCalledOnce()
      const csv = String(blobParts[0]?.[0] || '')
      expect(csv).toContain('id,when,library,path,status,progress,error')
      expect(csv).toContain('"Failed ""history"""')
      expect(csv).toContain('Network unavailable')
      expect(csv).toContain(
        'failed-1,—,"Failed ""history""",/storage/failed,Failed,1/2,Network unavailable',
      )
      expect(csv).not.toContain('Completed history')
      expect(click).toHaveBeenCalledOnce()
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(URL, 'createObjectURL', originalDescriptor)
      } else {
        Reflect.deleteProperty(URL, 'createObjectURL')
      }
    }
  })

  test('confirms clear-completed, posts with CSRF, then refreshes the scan list', async () => {
    const user = userEvent.setup()
    let cleared = false
    const fetchMock = vi.fn(async (url, init) => {
      if (String(url).includes('/api/scan_jobs_status')) {
        const currentJobs = cleared
          ? [{ id: 'active-1', library_name: 'Active history', status: 'Running' }]
          : [
              { id: 'done-1', library_name: 'Old history', status: 'Completed' },
              { id: 'active-1', library_name: 'Active history', status: 'Running' },
            ]
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          text: async () => JSON.stringify(currentJobs),
          json: async () => currentJobs,
        }
      }
      cleared = true
      return {
        ok: true,
        status: 200,
        redirected: false,
        url: 'http://localhost/clear_scan_jobs?status=Completed',
        headers: new Headers({ 'content-type': 'text/html' }),
      }
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.mocked(confirmAction).mockResolvedValue(true)

    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Old history')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear completed' }))
    await waitFor(() => expect(confirmAction).toHaveBeenCalled())
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url) === '/clear_scan_jobs?status=Completed' && init?.method === 'POST',
        ),
      ).toBe(true),
    )
    expect(await screen.findByText('Active history')).toBeInTheDocument()
    expect(screen.queryByText('Old history')).not.toBeInTheDocument()
    expect(screen.getByText('Cleared 1 Completed scan jobs.')).toBeInTheDocument()
  })

  test('clear all confirms terminal-only semantics and posts to the legacy endpoint', async () => {
    const user = userEvent.setup()
    let cleared = false
    const fetchMock = vi.fn(async (url, init) => {
      if (String(url).includes('/api/scan_jobs_status')) {
        const currentJobs = cleared
          ? [{ id: 'active-1', library_name: 'Active history', status: 'Running' }]
          : [
              { id: 'done-1', library_name: 'Completed history', status: 'Completed' },
              { id: 'failed-1', library_name: 'Failed history', status: 'Failed' },
              { id: 'cancelled-1', library_name: 'Cancelled history', status: 'Cancelled' },
              { id: 'active-1', library_name: 'Active history', status: 'Running' },
            ]
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          text: async () => JSON.stringify(currentJobs),
          json: async () => currentJobs,
        }
      }
      cleared = true
      return {
        ok: true,
        status: 200,
        redirected: false,
        url: 'http://localhost/clear_all_scan_jobs',
        headers: new Headers({ 'content-type': 'text/html' }),
      }
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.mocked(confirmAction).mockResolvedValue(true)

    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Cancelled history')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear all' }))
    await waitFor(() =>
      expect(confirmAction).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.stringContaining(
            'Running, stopping, queued, and scheduled scans will stay.',
          ),
        }),
      ),
    )
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url) === '/clear_all_scan_jobs' && init?.method === 'POST',
        ),
      ).toBe(true),
    )
    expect(await screen.findByText('Active history')).toBeInTheDocument()
    expect(screen.queryByText('Completed history')).not.toBeInTheDocument()
    expect(screen.queryByText('Cancelled history')).not.toBeInTheDocument()
    expect(
      screen.getByText(
        'Cleared 3 completed/failed/cancelled scan jobs (Running/Stopping/Queued/Scheduled kept).',
      ),
    ).toBeInTheDocument()
  })

  test('Refresh all while busy opens conflict modal and posts queue_policy', async () => {
    const user = userEvent.setup()
    vi.mocked(confirmAction).mockResolvedValue(true)
    const fetchMock = vi.fn(async (url, opts) => {
      if (String(url).includes('/api/scan_jobs_status')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => [{ id: '1', status: 'Running', library_name: 'PCWIN' }],
        }
      }
      if (String(url).includes('/api/admin/libraries/refresh_all')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({ status: 'queued', position: 2, count: 1 }),
        }
      }
      return {
        ok: false,
        status: 404,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({}),
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <ScansPage />
      </MemoryRouter>,
    )

    await screen.findByText(/Scanning PCWIN/i)
    await user.click(screen.getByRole('button', { name: /refresh all libraries/i }))
    await waitFor(() => expect(confirmAction).toHaveBeenCalled())
    expect(await screen.findByRole('heading', { name: /scan in progress/i })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /queue this scan/i }))
    await waitFor(() => {
      const refreshCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes('/api/admin/libraries/refresh_all'),
      )
      expect(refreshCall).toBeTruthy()
      const body = JSON.parse(refreshCall![1].body)
      expect(body.queue_policy).toBe(SCAN_QUEUE_POLICY.QUEUE)
      expect(body.force_parallel).toBe(false)
    })
  })
})

describe('LibrariesPage refresh all', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  test('idle Refresh all posts default queue_policy fields', async () => {
    const user = userEvent.setup()
    vi.mocked(confirmAction).mockResolvedValue(true)
    const fetchMock = vi.fn(async (url, opts) => {
      if (String(url).includes('/api/get_libraries')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => [{ uuid: 'lib-1', name: 'PCWIN' }],
        }
      }
      if (String(url).includes('/api/scan_jobs_status')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => [],
        }
      }
      if (String(url).includes('/api/admin/libraries/refresh_all')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({ status: 'started', count: 1, message: 'started' }),
        }
      }
      return {
        ok: false,
        status: 404,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({}),
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <LibrariesPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('PCWIN')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /refresh all libraries/i }))
    await waitFor(() => expect(confirmAction).toHaveBeenCalled())
    await waitFor(() => {
      const refreshCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes('/api/admin/libraries/refresh_all'),
      )
      expect(refreshCall).toBeTruthy()
      const body = JSON.parse(refreshCall![1].body)
      expect(body).toEqual({ queue_policy: 'queue', force_parallel: false })
    })
  })

  test('preserves the page shell and retries when the library roster fails', async () => {
    const libraryAttempts: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const requestUrl = String(url)
        if (requestUrl.includes('/api/get_libraries')) {
          libraryAttempts.push(requestUrl)
        }
        if (requestUrl.includes('/api/get_libraries') && libraryAttempts.length === 1) {
          return {
            ok: false,
            status: 503,
            headers: new Headers({ 'content-type': 'application/json' }),
            text: async () => JSON.stringify({ code: 'service_unavailable', detail: 'Try again.' }),
            json: async () => ({ code: 'service_unavailable', detail: 'Try again.' }),
          }
        }
        if (requestUrl.includes('/api/get_libraries')) {
          return {
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),
            text: async () => JSON.stringify([{ uuid: 'lib-1', name: 'PCWIN' }]),
            json: async () => [{ uuid: 'lib-1', name: 'PCWIN' }],
          }
        }
        return {
          ok: false,
          status: 404,
          headers: new Headers({ 'content-type': 'application/json' }),
          text: async () => JSON.stringify({ code: 'not_found', detail: 'Not found.' }),
          json: async () => ({ code: 'not_found', detail: 'Not found.' }),
        }
      }),
    )
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <LibrariesPage />
      </MemoryRouter>,
    )

    const retry = await screen.findByRole('button', { name: 'Retry loading libraries' })
    expect(screen.getByRole('heading', { name: 'Libraries & scans' })).toBeInTheDocument()
    await user.click(retry)
    expect(await screen.findByText('PCWIN')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Scan controls' })).toHaveAttribute(
      'href',
      '/admin/scan-controls',
    )
    expect(libraryAttempts).toHaveLength(2)
  })
})
