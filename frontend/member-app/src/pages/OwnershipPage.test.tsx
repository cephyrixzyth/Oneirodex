import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OwnershipPage } from './OwnershipPage'
import { ShellHarness } from '../testShell'
import { jsonResponse, requestHeaders, stubFetch } from '../testJsonResponse'
import { connection, connectionsBody, job } from '../components/stores/storeFixtures'

beforeEach(() => {
  document.head.innerHTML = '<meta name="csrf-token" content="csrf-test">'
})

afterEach(() => vi.unstubAllGlobals())

const LINKED_GOG = connection('gog', {
  state: 'connected',
  account: { connected: true, linked_at: null, updated_at: null },
  credential: { source: 'member', household_available: false },
  records: { owned: 12, matched: 5, needs_review: 4, last_recorded_at: null },
  actions: ['sync', 'reconnect', 'import_csv', 'disconnect'],
  last_sync: job({ synced: 12 }),
})

function renderPage({ shell = {}, route = '/ownership' } = {}) {
  return render(
    <ShellHarness shell={shell} router initialEntries={[route]}>
      <OwnershipPage />
    </ShellHarness>,
  )
}

test('Settings renders the shared connection list from the status contract', async () => {
  stubFetch(() =>
    jsonResponse(
      connectionsBody([
        LINKED_GOG,
        connection('humble', { state: 'unavailable', live: false, actions: [] }),
      ]),
    ),
  )
  renderPage()
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  expect(within(gog).getByText('12 titles · 5 matched · 4 to review')).toBeInTheDocument()
  expect(screen.getByText(/Not available yet: Humble Bundle/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'First-time setup' })).toHaveAttribute('href', '/welcome')
})

test('new chrome shows totals in the context bar and switches to match review', async () => {
  const user = userEvent.setup()
  const fetchMock = stubFetch((url: string) => {
    if (url.startsWith('/api/ownership/titles'))
      return jsonResponse({ ok: true, titles: [], next_after_id: null })
    return jsonResponse(connectionsBody([LINKED_GOG]))
  })
  renderPage({ shell: { enableNewChrome: true } })
  expect(await screen.findByText('12 owned · 5 matched · 4 to review')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Review matches' }))
  expect(await screen.findByText('Nothing is waiting for review.')).toBeInTheDocument()
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).startsWith('/api/ownership/titles?after_id=0&status=needs_review'),
    ),
  ).toBe(true)
})

test('a failed status read offers a retry', async () => {
  const user = userEvent.setup()
  let calls = 0
  stubFetch(() => {
    calls += 1
    return calls === 1
      ? jsonResponse(
          { ok: false, error: 'boom', error_code: 'internal' },
          { ok: false, status: 500 },
        )
      : jsonResponse(connectionsBody([LINKED_GOG]))
  })
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('listitem', { name: 'GOG' })).toBeInTheDocument()
})

test('sync posts to the store route with the CSRF header', async () => {
  const user = userEvent.setup()
  const fetchMock = stubFetch((url: string, init: any) => {
    if (url === '/api/ownership/gog/sync' && init?.method === 'POST') {
      return jsonResponse({
        ok: true,
        synced: 12,
        matched: 6,
        store: 'gog',
        job: job({ synced: 12, matched: 6 }),
      })
    }
    return jsonResponse(connectionsBody([LINKED_GOG]))
  })
  renderPage()
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  await user.click(within(gog).getByRole('button', { name: 'Sync now' }))
  const call = fetchMock.mock.calls.find(
    ([url, init]: any) => url === '/api/ownership/gog/sync' && init?.method === 'POST',
  )
  expect(requestHeaders(call).get('X-CSRFToken')).toBe('csrf-test')
  expect(
    await within(gog).findByText('Synced 12 titles (6 matched to your library).'),
  ).toBeInTheDocument()
})
