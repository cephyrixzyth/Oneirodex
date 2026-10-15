import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../App'
import { StoragePage } from './StoragePage'

const STATUS_HELPERS_OFF = {
  helpers_enabled: false,
  allow_apply: false,
  games_path: '/storage',
  games_exists: true,
  games_readable: true,
  games_writable: true,
  degrade_reason: null,
}

const STATUS_APPLY_OFF = {
  helpers_enabled: true,
  allow_apply: false,
  games_path: '/storage',
  games_exists: true,
  games_readable: true,
  games_writable: true,
  degrade_reason: 'Apply disabled (ALLOW_HARDLINK_APPLY=false)',
}

const STATUS_RO = {
  helpers_enabled: true,
  allow_apply: false,
  games_path: '/storage',
  games_exists: true,
  games_readable: true,
  games_writable: false,
  degrade_reason: 'Apply disabled (ALLOW_HARDLINK_APPLY=false); games path is read-only',
}

const PREVIEW_OK = {
  ok: true,
  same_volume: true,
  would_succeed: true,
  bytes_saved_estimate: 2048,
  reasons: [],
  source: 'C:\\games\\a.exe',
  dest: 'C:\\library\\a.exe',
}

function mockFetch(handlers: any) {
  return vi.fn(async (url, init) => {
    const method = (init?.method || 'GET').toUpperCase()
    const key = `${method} ${String(url)}`
    for (const [match, fn] of handlers) {
      if (key.includes(match) || String(url).includes(match)) {
        const result = await fn(url, init, method)
        if (result) return result
      }
    }
    throw new Error(`unexpected fetch ${method} ${url}`)
  })
}

function jsonOk(body: any, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => body,
  }
}

test('StoragePage shows helpers-off and apply-off banners from status', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch([['/api/storage/status', async () => jsonOk(STATUS_HELPERS_OFF)]])
  try {
    render(<StoragePage />)
    expect(await screen.findByRole('heading', { name: 'Storage / hardlinks' })).toBeInTheDocument()
    expect(await screen.findByText(/Hardlink helpers are/i)).toBeInTheDocument()
    // Scoped to the readiness strip (UID-014). A bare /off/i now matches both
    // the banner and the strip's Helpers tile, and an ambiguous query that
    // passed only while the page had one "off" on it was never asserting
    // anything specific.
    const strip = screen.getByLabelText('Storage readiness')
    expect(within(strip).getByText('Off')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('StoragePage shows apply-off safety banner and RO games mount banner', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch([['/api/storage/status', async () => jsonOk(STATUS_RO)]])
  try {
    render(<StoragePage />)
    expect(await screen.findByText(/Apply is disabled until/i)).toBeInTheDocument()
    expect(screen.getByText(/Games mount is/i)).toBeInTheDocument()
    expect(screen.getByText(/games path is read-only/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('StoragePage preview happy path shows reasons list and bytes estimate', async () => {
  const user = userEvent.setup()
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch([
    ['/api/storage/status', async () => jsonOk(STATUS_APPLY_OFF)],
    [
      '/api/storage/hardlink/preview',
      async (_url: any, init: any, method: any) => {
        if (method !== 'POST') return null
        const body = init?.body ? JSON.parse(init.body) : {}
        expect(body.source).toBe('C:\\games\\a.exe')
        expect(body.dest).toBe('C:\\library\\a.exe')
        return jsonOk(PREVIEW_OK)
      },
    ],
  ])
  try {
    render(<StoragePage />)
    expect(await screen.findByRole('button', { name: 'Preview' })).toBeEnabled()
    await user.type(screen.getByLabelText('Source file'), 'C:\\games\\a.exe')
    await user.type(screen.getByLabelText('Destination path'), 'C:\\library\\a.exe')
    await user.click(screen.getByRole('button', { name: 'Preview' }))
    await waitFor(() => {
      expect(screen.getByText(/Would succeed/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/Same volume:/i)).toBeInTheDocument()
    expect(screen.getByText('Yes')).toBeInTheDocument()
    expect(screen.getByText(/2\.0 KB/i)).toBeInTheDocument()
    expect(screen.getByText(/Reasons: none/i)).toBeInTheDocument()
    expect(screen.getByText('Raw JSON')).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('App route /admin/storage mounts Storage UI', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch([['/api/storage/status', async () => jsonOk(STATUS_APPLY_OFF)]])
  try {
    render(
      <MemoryRouter initialEntries={['/admin/storage']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: 'Storage / hardlinks' })).toBeInTheDocument()
    expect(screen.getByLabelText('Source file')).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('StoragePage hides the readiness strip when status could not be read', async () => {
  // statusLoaded is set in a `finally`, so it is true after a failure too, with
  // `status` reset to EMPTY_STATUS. Gating the strip on it alone rendered
  // "Games mount: Missing" in alarm red for a reading that never arrived —
  // a confident answer to a question we could not ask.
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch([
    [
      '/api/storage/status',
      async () => ({
        ok: false,
        status: 503,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({}),
      }),
    ],
  ])
  try {
    render(<StoragePage />)

    expect(await screen.findByRole('heading', { name: 'Storage / hardlinks' })).toBeInTheDocument()
    // The banner explains the failure; the strip must not also assert findings.
    expect(await screen.findByText(/Status API unavailable/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Storage readiness')).toBeNull()
    expect(screen.queryByText(/Hardlink helpers are/i)).toBeNull()
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Retry storage status' })).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})
