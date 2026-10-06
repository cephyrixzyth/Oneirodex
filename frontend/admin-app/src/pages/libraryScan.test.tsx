import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { LibrariesPage } from './LibrariesPage'
import { ScansPage } from './ScansPage'

/**
 * Per-library Scan, and Scan again on a finished job (W28).
 *
 * The SPA only ever had "Refresh all libraries". `/api/admin/libraries/scan`
 * has always taken a single `library_uuid`, and the Jinja scan manager has
 * always offered a restart — but neither control existed here, so scanning one
 * library or re-running a failed job meant leaving the SPA.
 */

function jsonResponse(data: any, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => data,
  }
}

const LIBRARIES = [
  { uuid: 'lib-1', name: 'PCWIN', last_scan_folder: '/storage/pc' },
  { uuid: 'lib-2', name: 'PS2', last_scan_folder: '' },
]

let calls: any

function installFetch(overrides: { jobs?: any; scan?: any } = {}) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, opts) => {
      const href = String(url)
      calls.push({ url: href, body: opts?.body ? JSON.parse(opts.body) : null })
      if (href.includes('/api/admin/library_platforms')) {
        return jsonResponse({
          platforms: [{ key: 'NES', label: 'Nintendo Entertainment System (NES)' }],
        })
      }
      if (href.includes('/api/get_libraries')) return jsonResponse(LIBRARIES)
      if (href.includes('/api/scan_jobs_status')) {
        return jsonResponse(overrides.jobs ?? [])
      }
      if (href.includes('/api/admin/libraries/scan')) {
        return jsonResponse(
          overrides.scan ?? { status: 'started', job_id: 'job-9', message: 'Scan started.' },
        )
      }
      return jsonResponse({}, { ok: false, status: 404 })
    }),
  )
}

beforeEach(() => {
  installFetch()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('each library row can start its own scan', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <LibrariesPage />
    </MemoryRouter>,
  )

  expect(await screen.findByText('PCWIN')).toBeInTheDocument()
  const scanButtons = screen.getAllByRole('button', { name: 'Scan' })
  expect(scanButtons).toHaveLength(2)

  await user.click(scanButtons[0])

  await waitFor(() => {
    expect(calls.some((c: any) => c.url.includes('/api/admin/libraries/scan'))).toBe(true)
  })
  const posted: any = calls.find((c: any) => c.url.includes('/api/admin/libraries/scan'))
  expect(posted.body.library_uuid).toBe('lib-1')
  // Idle path still sends the queue fields — never omit them on a start, or the
  // backend has to guess the policy.
  expect(posted.body.queue_policy).toBe('queue')
  expect(posted.body.force_parallel).toBe(false)
})

test('manual create form creates a library and queues its first scan', async () => {
  const user = userEvent.setup()
  const seen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, opts) => {
      const href = String(url)
      seen.push(href)
      if (href.includes('/api/admin/library_platforms')) {
        return jsonResponse({
          platforms: [{ key: 'NES', label: 'Nintendo Entertainment System (NES)' }],
        })
      }
      if (href.includes('/api/get_libraries')) {
        return jsonResponse([{ uuid: 'new-lib', name: 'NES Games' }])
      }
      if (href.includes('/admin/library/add')) {
        expect((opts?.body as FormData).get('name')).toBe('NES Games')
        expect((opts?.body as FormData).get('platform')).toBe('NES')
        return { ...jsonResponse({}), redirected: true, url: 'http://localhost/libraries' }
      }
      if (href.includes('/api/admin/libraries/scan')) {
        const body = JSON.parse(opts?.body as string)
        expect(body).toMatchObject({
          library_uuid: 'new-lib',
          folder: '/storage/games/nes',
          scan_mode: 'folders',
        })
        return jsonResponse({ status: 'queued' })
      }
      return jsonResponse({}, { ok: false, status: 404 })
    }),
  )

  render(
    <MemoryRouter>
      <LibrariesPage />
    </MemoryRouter>,
  )
  await user.type(await screen.findByLabelText('Library name'), 'NES Games')
  await user.selectOptions(screen.getByLabelText('Platform'), 'NES')
  await user.type(screen.getByLabelText('Folder path inside the server'), '/storage/games/nes')
  await user.click(screen.getByRole('button', { name: 'Create library and start scan' }))

  expect(await screen.findByText('Created and queued first scan.')).toBeInTheDocument()
  expect(seen.some((url) => url.includes('/admin/library/add'))).toBe(true)
  expect(seen.some((url) => url.includes('/api/admin/libraries/scan'))).toBe(true)
})

test('a library with no last scan folder says so instead of posting', async () => {
  render(
    <MemoryRouter>
      <LibrariesPage />
    </MemoryRouter>,
  )

  await screen.findByText('PS2')
  const buttons = screen.getAllByRole('button', { name: 'Scan' })
  // Row order is name-ascending: PCWIN, PS2.
  expect(buttons[1]).toBeDisabled()
  expect(buttons[1]).toHaveAttribute('title', expect.stringContaining('No last scan folder'))
})

test('a finished job offers Scan again and repeats that job, not the library', async () => {
  const user = userEvent.setup()
  installFetch({
    jobs: [
      {
        id: 'job-1',
        library_name: 'PCWIN',
        library_uuid: 'lib-1',
        status: 'Failed',
        scan_folder: '/storage/pc/retro',
        setting_filefolder: true,
        setting_remove: true,
        setting_download_missing_images: false,
      },
    ],
  })

  render(
    <MemoryRouter>
      <ScansPage />
    </MemoryRouter>,
  )

  const retry = await screen.findByRole('button', { name: 'Scan again' })
  await user.click(retry)

  await waitFor(() => {
    expect(calls.some((c: any) => c.url.includes('/api/admin/libraries/scan'))).toBe(true)
  })
  const posted: any = calls.find((c: any) => c.url.includes('/api/admin/libraries/scan'))
  // The job's own folder and its own settings — a retry, not a fresh scan of
  // wherever the library happens to point now.
  expect(posted.body).toMatchObject({
    library_uuid: 'lib-1',
    folder: '/storage/pc/retro',
    scan_mode: 'files',
    remove_missing: true,
    download_missing_images: false,
  })
})

test('a running job has nothing to retry', async () => {
  installFetch({
    jobs: [
      {
        id: 'job-1',
        library_name: 'PCWIN',
        library_uuid: 'lib-1',
        status: 'Running',
        scan_folder: '/storage/pc',
      },
    ],
  })

  render(
    <MemoryRouter>
      <ScansPage />
    </MemoryRouter>,
  )

  await screen.findByText('PCWIN')
  expect(screen.queryByRole('button', { name: 'Scan again' })).toBeNull()
})
