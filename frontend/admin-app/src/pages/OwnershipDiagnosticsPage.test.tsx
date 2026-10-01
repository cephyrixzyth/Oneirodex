import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { OwnershipDiagnosticsPage } from './OwnershipDiagnosticsPage'
import { showToast } from '../utils/toast'

vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))

function response(body: unknown, status = 200) {
  const text = JSON.stringify(body)
  return Promise.resolve({
    ok: status < 400,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(text),
  })
}

function store(provider: string, name: string, overrides: any = {}) {
  return {
    provider,
    name,
    state: 'connected',
    live: true,
    cancellable: provider === 'gog',
    setup: { ready: true, missing: null },
    credential: { source: 'member', household_available: false },
    account: { connected: true, linked_at: null, updated_at: null },
    records: { owned: 4, matched: 2, needs_review: 1, last_recorded_at: null },
    last_sync: null,
    previous_failure: null,
    admin_actions: ['sync'],
    ...overrides,
  }
}

const BODY = {
  ok: true,
  schema_version: 1,
  household: {
    sync_enabled: true,
    steam_server_key: false,
    unofficial_opt_in: [],
    household_tokens: { gog: true, epic: false },
    optional_packages: {},
  },
  members: [
    {
      user_id: 2,
      name: 'Riley',
      stores: [
        store('gog', 'GOG', { credential: { source: 'household', household_available: true } }),
        store('epic', 'Epic Games', {
          state: 'reauth_required',
          admin_actions: [],
          last_sync: {
            status: 'failed',
            outcome: {
              reason: 'credential_rejected',
              message:
                'Epic Games rejected the saved sign-in (expired or revoked). Reconnect with a fresh one; CSV import still works.',
              action: 'reconnect',
              retryable: false,
              audience: 'member',
            },
          },
        }),
      ],
    },
  ],
  next_after_id: null,
  stale_running_jobs: 0,
}

afterEach(() => vi.unstubAllGlobals())

function renderPage() {
  return render(
    <MemoryRouter>
      <OwnershipDiagnosticsPage />
    </MemoryRouter>,
  )
}

test('shows redacted per-member state, household presence and repair only where it can help', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => response(BODY)),
  )
  renderPage()
  expect(await screen.findByRole('heading', { name: 'Store connections' })).toBeInTheDocument()
  expect(screen.getByText('Not configured')).toBeInTheDocument()
  expect(screen.getByText(/Rows marked “Household sign-in”/)).toBeInTheDocument()
  const gogRow = screen.getByRole('row', { name: /GOG/ })
  expect(within(gogRow).getByText('Household sign-in')).toBeInTheDocument()
  expect(within(gogRow).getByRole('button', { name: 'Retry sync' })).toBeEnabled()
  const epicRow = screen.getByRole('row', { name: /Epic Games/ })
  expect(within(epicRow).getByText('Reconnect needed')).toBeInTheDocument()
  expect(within(epicRow).getByText(/expired or revoked/)).toBeInTheDocument()
  expect(within(epicRow).queryByRole('button')).toBeNull()
})

test('retry posts the admin route for that member and store, then reloads', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn((url: string, init?: any) =>
    init?.method === 'POST' ? response({ ok: true, job: { status: 'succeeded' } }) : response(BODY),
  )
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Retry sync' }))
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          url === '/api/admin/ownership/connections/2/gog/sync' && init?.method === 'POST',
      ),
    ).toBe(true),
  )
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.filter(([, init]) => !init?.method || init.method === 'GET').length,
    ).toBeGreaterThanOrEqual(2),
  )
})

test('a failed load says so and offers a retry', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => response({ ok: false, error: 'nope', error_code: 'internal' }, 500)),
  )
  renderPage()
  expect(
    await screen.findByText('Unable to load store connection diagnostics.'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
})

test('a repair on a later page re-reads every page shown, so that member stays in view', async () => {
  const user = userEvent.setup()
  const page1 = { ...BODY, next_after_id: 2, stale_running_jobs: 1 }
  const page2 = {
    ...BODY,
    members: [{ user_id: 9, name: 'Sam', stores: [store('gog', 'GOG')] }],
    next_after_id: null,
    stale_running_jobs: 1,
  }
  const fetchMock = vi.fn((url: string, init?: any) => {
    if (init?.method === 'POST') return response({ ok: true, job: { status: 'succeeded' } })
    return response(url.includes('after_id=2') ? page2 : page1)
  })
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Show more members' }))
  const samRow = await screen.findByRole('row', { name: /Sam/ })
  expect(screen.getByText(/2 sync\(s\) stopped without finishing/)).toBeInTheDocument()
  await user.click(within(samRow).getByRole('button', { name: 'Retry sync' }))
  await waitFor(() =>
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('after_id=2')).length).toBe(
      2,
    ),
  )
  expect(await screen.findByRole('row', { name: /Sam/ })).toBeInTheDocument()
  expect(screen.getByRole('row', { name: /Riley.*GOG|GOG.*Riley/ })).toBeInTheDocument()
  expect(screen.getByText(/2 sync\(s\) stopped without finishing/)).toBeInTheDocument()
})

test('Show more members fetches a page once, however often it is clicked', async () => {
  const user = userEvent.setup()
  let release: () => void = () => {}
  const page2 = {
    ...BODY,
    members: [{ user_id: 9, name: 'Sam', stores: [store('gog', 'GOG')] }],
    next_after_id: null,
    stale_running_jobs: 0,
  }
  const fetchMock = vi.fn((url: string) => {
    if (url.includes('after_id=2'))
      return new Promise((resolve) => {
        release = () => resolve(response(page2))
      })
    return response({ ...BODY, next_after_id: 2 })
  })
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  const more = await screen.findByRole('button', { name: 'Show more members' })
  await user.click(more)
  await user.click(screen.getByRole('button', { name: 'Loading…' }))
  release()
  expect(await screen.findByRole('row', { name: /Sam/ })).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('after_id=2'))).toHaveLength(1)
  expect(screen.getAllByRole('row', { name: /Sam/ })).toHaveLength(1)
})

test('a sign-in saved before the upgrade is labelled as of unknown origin', async () => {
  const body = {
    ...BODY,
    members: [
      {
        user_id: 2,
        name: 'Riley',
        stores: [
          store('gog', 'GOG', { credential: { source: 'unknown', household_available: true } }),
        ],
      },
    ],
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(() => response(body)),
  )
  renderPage()
  const row = await screen.findByRole('row', { name: /GOG/ })
  expect(within(row).getByText('Unknown (saved before upgrade)')).toBeInTheDocument()
})

test('a later page that fails to load says so', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      url.includes('after_id=2')
        ? response({ ok: false, error: 'Server error', error_code: 'internal' }, 500)
        : response({ ...BODY, next_after_id: 2 }),
    ),
  )
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Show more members' }))
  await waitFor(() =>
    expect(showToast).toHaveBeenCalledWith(
      expect.stringMatching(/Server error|Unable to load more members/),
      'error',
    ),
  )
  expect(screen.getByRole('row', { name: /Riley.*GOG|GOG.*Riley/ })).toBeInTheDocument()
})
