import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { LibrariesPage } from './LibrariesPage'
import { ScansPage } from './ScansPage'
import { SCAN_QUEUE_POLICY } from '../components/scanQueuePolicy'

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
      expect(screen.getByText(/Queued/)).toBeInTheDocument()
    })
    expect(screen.getByText(/\(#1\)/)).toBeInTheDocument()
    expect(screen.getByText('PCWIN')).toBeInTheDocument()
    expect(screen.getByText('PS2')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/Scanning/i)
    expect(screen.getByRole('region', { name: 'Recent scan jobs table' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Dupe glance' })).not.toBeInTheDocument()
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

  test('Refresh all while busy opens conflict modal and posts queue_policy', async () => {
    const user = userEvent.setup()
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
    // The house dialog, not window.confirm (UID-042) — its named button commits.
    await user.click(await screen.findByRole('button', { name: /^refresh all$/i }))
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
    // The house dialog, not window.confirm (UID-042) — its named button commits.
    await user.click(await screen.findByRole('button', { name: /^refresh all$/i }))
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
