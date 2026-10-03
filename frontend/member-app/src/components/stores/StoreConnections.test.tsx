import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StoreConnections, SYNC_POLL_MS } from './StoreConnections'
import { connection, connectionsBody, job } from './storeFixtures'
import { jsonResponse, requestHeaders, stubFetch } from '../../testJsonResponse'

/** Focus moves after a poll re-render; allow for a loaded CI box. */
const FOCUS_WAIT = { timeout: 3000 }

vi.mock('@oneirodex/ui', async (importOriginal) => ({
  ...(await importOriginal<any>()),
  confirmAction: vi.fn(() => Promise.resolve(true)),
}))

beforeEach(() => {
  document.head.innerHTML = '<meta name="csrf-token" content="csrf-test">'
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function card(name: string) {
  return screen.getByRole('listitem', { name })
}

test('renders only the actions the server lists for each state', async () => {
  stubFetch(() =>
    jsonResponse(
      connectionsBody([
        connection('gog', {
          state: 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'member', household_available: false },
          actions: ['sync', 'reconnect', 'import_csv', 'disconnect'],
          last_sync: job(),
        }),
        connection('steam', {
          state: 'not_configured',
          setup: { ready: false, missing: 'server_key' },
          actions: ['import_csv'],
        }),
        connection('meta_quest', { state: 'import_only', live: false, actions: ['import_csv'] }),
        connection('humble', { state: 'unavailable', live: false, actions: [] }),
      ]),
    ),
  )
  render(<StoreConnections />)
  await screen.findByRole('heading', { name: 'Keep in sync' })
  const gog = card('GOG')
  expect(within(gog).getByText('Linked')).toBeInTheDocument()
  expect(within(gog).getByRole('button', { name: 'Sync now' })).toBeEnabled()
  expect(within(gog).queryByRole('button', { name: 'Stop sync' })).toBeNull()
  const steam = card('Steam')
  expect(within(steam).getByText('Needs server setup')).toBeInTheDocument()
  expect(within(steam).queryByRole('button', { name: 'Sync now' })).toBeNull()
  expect(
    within(steam).getByText(/server key your administrator has not configured/),
  ).toBeInTheDocument()
  expect(
    within(card('Meta Quest'))
      .getAllByRole('button')
      .map((b) => b.textContent),
  ).toEqual(['Import a list'])
  expect(screen.queryByRole('listitem', { name: 'Humble Bundle' })).toBeNull()
  expect(screen.getByText(/Not available yet: Humble Bundle/)).toBeInTheDocument()
})

test('an expired sign-in offers reconnect, not a doomed retry, and shows the catalogue sentence', async () => {
  stubFetch(() =>
    jsonResponse(
      connectionsBody([
        connection('gog', {
          state: 'reauth_required',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'member', household_available: false },
          actions: ['reconnect', 'import_csv', 'disconnect'],
          last_sync: job({
            status: 'failed',
            outcome: {
              reason: 'credential_rejected',
              message:
                'GOG rejected the saved sign-in (expired or revoked). Reconnect with a fresh one; CSV import still works.',
              action: 'reconnect',
              retryable: false,
              audience: 'member',
            },
          }),
        }),
      ]),
    ),
  )
  render(<StoreConnections />)
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  expect(within(gog).getByText('Reconnect needed')).toBeInTheDocument()
  expect(within(gog).getByText(/expired or revoked/)).toBeInTheDocument()
  expect(within(gog).queryByRole('button', { name: /Sync now|Try again/ })).toBeNull()
  expect(within(gog).getByRole('button', { name: 'Reconnect' })).toHaveClass('od-btn--primary')
})

test('stop is offered only while a cancellable sync runs, and posts the cancel route', async () => {
  const user = userEvent.setup()
  const running = job({
    status: 'running',
    finished_at: null,
    progress: { pages: 2, items_seen: 100 },
  })
  const fetchMock = stubFetch((url: string) => {
    if (url.endsWith('/sync/cancel'))
      return jsonResponse(
        { ok: true, job: { ...running, cancel_requested: true } },
        { status: 202 },
      )
    return jsonResponse(
      connectionsBody([
        connection('gog', {
          state: 'syncing',
          account: { connected: true, linked_at: null, updated_at: null },
          actions: ['cancel'],
          last_sync: running,
        }),
        connection('steam', {
          state: 'syncing',
          cancellable: false,
          account: { connected: true, linked_at: null, updated_at: null },
          actions: [],
          last_sync: job({
            store: 'steam',
            status: 'running',
            cancellable: false,
            finished_at: null,
          }),
        }),
      ]),
    )
  })
  render(<StoreConnections />)
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  expect(within(gog).getByText(/100 titles so far/)).toBeInTheDocument()
  expect(within(card('Steam')).queryByRole('button', { name: 'Stop sync' })).toBeNull()
  await user.click(within(gog).getByRole('button', { name: 'Stop sync' }))
  const cancel = fetchMock.mock.calls.find(([url]) =>
    String(url).endsWith('/api/ownership/gog/sync/cancel'),
  )
  expect(cancel).toBeTruthy()
  expect(requestHeaders(cancel).get('X-CSRFToken')).toBe('csrf-test')
  expect(await within(gog).findByText(/Nothing from this sync will be saved/)).toBeInTheDocument()
})

test('while a sync runs the list re-reads its status, and stops once it ends', async () => {
  expect(SYNC_POLL_MS).toBe(2000)
  let reads = 0
  stubFetch(() => {
    reads += 1
    const running = reads < 3
    return jsonResponse(
      connectionsBody([
        connection('epic', {
          state: running ? 'syncing' : 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'member', household_available: false },
          actions: running ? ['cancel'] : ['sync', 'reconnect', 'import_csv', 'disconnect'],
          last_sync: job({
            store: 'epic',
            status: running ? 'running' : 'succeeded',
            finished_at: running ? null : '2026-09-28T10:01:00Z',
          }),
        }),
      ]),
    )
  })
  render(<StoreConnections pollMs={20} />)
  await screen.findByRole('listitem', { name: 'Epic Games' })
  expect(await screen.findByRole('button', { name: 'Sync now' })).toBeInTheDocument()
  const settled = reads
  await act(() => new Promise((resolve) => setTimeout(resolve, 100)))
  expect(reads).toBe(settled)
})

test('a failed sync shows the server sentence, never raw provider text', async () => {
  const user = userEvent.setup()
  stubFetch((url: string, init: any) => {
    if (url.endsWith('/sync') && init?.method === 'POST') {
      return jsonResponse(
        {
          ok: false,
          error: 'Steam did not answer correctly. Try again later.',
          error_code: 'bad_gateway',
          detail: {
            reason: 'upstream_unavailable',
            message: 'Steam did not answer correctly. Try again later.',
            action: 'retry_later',
            retryable: true,
            audience: 'member',
          },
        },
        { ok: false, status: 502 },
      )
    }
    return jsonResponse(
      connectionsBody([
        connection('steam', {
          state: 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'not_required', household_available: false },
          actions: ['sync', 'reconnect', 'import_csv', 'disconnect'],
        }),
      ]),
    )
  })
  render(<StoreConnections />)
  const steam = await screen.findByRole('listitem', { name: 'Steam' })
  await user.click(within(steam).getByRole('button', { name: 'Sync now' }))
  expect(await within(steam).findByRole('alert')).toHaveTextContent(
    'Steam did not answer correctly. Try again later.',
  )
})

test('linking sends only filled fields, uses a password input for tokens and explains the household sign-in', async () => {
  const user = userEvent.setup()
  const fetchMock = stubFetch((url: string, init: any) => {
    if (url === '/api/ownership/gog' && init?.method === 'POST')
      return jsonResponse({ ok: true, account: { store: 'gog' } }, { status: 201 })
    // The server's shape for an unlinked store with a household token: the
    // source a link *would* use, not a sync that is happening.
    return jsonResponse(
      connectionsBody([
        connection('gog', { credential: { source: 'household', household_available: true } }),
      ]),
    )
  })
  render(<StoreConnections />)
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  expect(
    within(gog).getByText(/If you leave the token blank, the household sign-in/),
  ).toBeInTheDocument()
  expect(within(gog).queryByText(/Syncing with the household sign-in/)).toBeNull()
  await user.click(within(gog).getByRole('button', { name: 'Link account' }))
  const token = within(gog).getByLabelText(/GOG refresh token/)
  expect(token).toHaveAttribute('type', 'password')
  expect(token).not.toBeRequired()
  // Not a site login: password managers skip it and never offer or save the member's password here.
  expect(token.closest('form')).toHaveAttribute('data-form-type', 'other')
  expect(token).toHaveAttribute('autocomplete', 'one-time-code')
  expect(token).toHaveAttribute('data-1p-ignore')
  expect(token).toHaveAttribute('data-bwignore')
  await user.type(token, 'refresh-secret')
  await user.click(within(gog).getByRole('button', { name: 'Save link' }))
  const post = fetchMock.mock.calls.find(
    ([url, init]: any) => url === '/api/ownership/gog' && init?.method === 'POST',
  )
  expect(JSON.parse(post![1].body)).toEqual({ refresh_token: 'refresh-secret' })
  expect(await within(gog).findByText(/GOG link saved/)).toBeInTheDocument()
})

test('csv import reports imported, matched and skipped rows', async () => {
  const user = userEvent.setup()
  stubFetch((url: string, init: any) => {
    if (url === '/api/ownership/meta_quest/csv')
      return jsonResponse({ ok: true, imported: 2, matched: 1, skipped: 1 })
    return jsonResponse(
      connectionsBody([
        connection('meta_quest', { state: 'import_only', live: false, actions: ['import_csv'] }),
      ]),
    )
  })
  render(<StoreConnections />)
  const quest = await screen.findByRole('listitem', { name: 'Meta Quest' })
  await user.click(within(quest).getByRole('button', { name: 'Import a list' }))
  await user.type(within(quest).getByLabelText(/Paste a list/), '1,A{enter}2,B')
  await user.click(within(quest).getByRole('button', { name: 'Import' }))
  expect(
    await within(quest).findByText('Imported 2 titles (1 matched, 1 skipped).'),
  ).toBeInTheDocument()
})

test('arrow keys move between actions for keyboard and controller users', async () => {
  const user = userEvent.setup()
  stubFetch(() =>
    jsonResponse(
      connectionsBody([
        connection('gog', {
          state: 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'member', household_available: false },
          actions: ['sync', 'reconnect', 'import_csv', 'disconnect'],
        }),
        connection('epic'),
      ]),
    ),
  )
  render(<StoreConnections />)
  const sync = await screen.findByRole('button', { name: 'Sync now' })
  sync.focus()
  await user.keyboard('{ArrowDown}')
  expect(screen.getByRole('button', { name: 'Reconnect' })).toHaveFocus()
  await user.keyboard('{End}')
  expect(within(card('Epic Games')).getByRole('button', { name: 'Import a list' })).toHaveFocus()
  await user.keyboard('{Home}')
  expect(sync).toHaveFocus()
})

test('store ownership turned off says so instead of rendering controls', async () => {
  stubFetch(() =>
    jsonResponse(connectionsBody([connection('gog', { state: 'disabled', actions: [] })], false)),
  )
  render(<StoreConnections />)
  expect(await screen.findByText(/turned off by your administrator/)).toBeInTheDocument()
  expect(screen.queryByRole('button')).toBeNull()
})

test('reconnect keeps the saved label, needs a token, and returns focus to Reconnect', async () => {
  const user = userEvent.setup()
  let saved = false
  const fetchMock = stubFetch((url: string, init: any) => {
    if (url === '/api/ownership/gog' && init?.method === 'POST') {
      saved = true
      return jsonResponse({ ok: true, account: { store: 'gog' } }, { status: 201 })
    }
    return jsonResponse(
      connectionsBody([
        connection('gog', {
          state: saved ? 'connected' : 'reauth_required',
          account: {
            connected: true,
            linked_at: null,
            updated_at: null,
            external_account_id: 'my-gog',
          },
          credential: { source: 'member', household_available: false },
          actions: saved
            ? ['sync', 'reconnect', 'import_csv', 'disconnect']
            : ['reconnect', 'import_csv', 'disconnect'],
        }),
      ]),
    )
  })
  render(<StoreConnections />)
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  await user.click(within(gog).getByRole('button', { name: 'Reconnect' }))
  expect(within(gog).getByLabelText(/GOG user ID or label/)).toHaveValue('my-gog')
  const token = within(gog).getByLabelText(/GOG refresh token/)
  expect(token).toBeRequired()
  await user.type(token, 'fresh-token')
  await user.click(within(gog).getByRole('button', { name: 'Save link' }))
  const post = fetchMock.mock.calls.find(
    ([url, init]: any) => url === '/api/ownership/gog' && init?.method === 'POST',
  )
  expect(JSON.parse(post![1].body)).toEqual({ gog_user_id: 'my-gog', refresh_token: 'fresh-token' })
  expect(
    await within(gog).findByText('GOG link saved. Sync to read your library.'),
  ).toBeInTheDocument()
  expect(within(gog).getByRole('button', { name: 'Reconnect' })).toHaveFocus()
})

test('a save that leaves the store still needing a sign-in says so', async () => {
  const user = userEvent.setup()
  stubFetch((url: string, init: any) => {
    if (url === '/api/ownership/epic' && init?.method === 'POST')
      return jsonResponse({ ok: true, account: { store: 'epic' } }, { status: 201 })
    return jsonResponse(
      connectionsBody([
        connection('epic', {
          state: 'needs_credential',
          account: {
            connected: true,
            linked_at: null,
            updated_at: null,
            external_account_id: null,
          },
          actions: ['reconnect', 'import_csv', 'disconnect'],
        }),
      ]),
    )
  })
  render(<StoreConnections />)
  const epic = await screen.findByRole('listitem', { name: 'Epic Games' })
  await user.click(within(epic).getByRole('button', { name: 'Reconnect' }))
  await user.type(within(epic).getByLabelText(/Epic device auth JSON/), 'not-json')
  await user.click(within(epic).getByRole('button', { name: 'Save link' }))
  expect(await within(epic).findByText(/still needs a working sign-in/)).toBeInTheDocument()
  expect(within(epic).queryByText(/Sync to read your library/)).toBeNull()
})

test('focus stays on the card when Sync turns into Stop and back', async () => {
  const user = userEvent.setup()
  let running = false
  let finish: () => void = () => {}
  stubFetch((url: string, init: any) => {
    if (url.endsWith('/sync') && init?.method === 'POST') {
      running = true
      return new Promise((resolve) => {
        finish = () => {
          running = false
          resolve(jsonResponse({ ok: true, synced: 3, matched: 1, job: job() }))
        }
      })
    }
    return jsonResponse(
      connectionsBody([
        connection('gog', {
          state: running ? 'syncing' : 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'member', household_available: false },
          actions: running ? ['cancel'] : ['sync', 'reconnect', 'import_csv', 'disconnect'],
          last_sync: running ? job({ status: 'running', finished_at: null }) : job(),
        }),
      ]),
    )
  })
  render(<StoreConnections pollMs={20} />)
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  const sync = within(gog).getByRole('button', { name: 'Sync now' })
  sync.focus()
  await user.keyboard('{Enter}')
  await waitFor(
    () => expect(within(gog).getByRole('button', { name: 'Stop sync' })).toHaveFocus(),
    FOCUS_WAIT,
  )
  await act(async () => finish())
  await waitFor(
    () => expect(within(gog).getByRole('button', { name: 'Sync now' })).toHaveFocus(),
    FOCUS_WAIT,
  )
})

test('focus the member moved to another card is never pulled back when a slow import finishes', async () => {
  const user = userEvent.setup()
  let finish: () => void = () => {}
  stubFetch((url: string) => {
    if (url === '/api/ownership/epic/csv') {
      return new Promise((resolve) => {
        finish = () => resolve(jsonResponse({ ok: true, imported: 1, matched: 0 }))
      })
    }
    return jsonResponse(connectionsBody([connection('epic'), connection('gog')]))
  })
  render(<StoreConnections />)
  const epic = await screen.findByRole('listitem', { name: 'Epic Games' })
  await user.click(within(epic).getByRole('button', { name: 'Import a list' }))
  await user.type(within(epic).getByLabelText(/Paste a list/), 'fn,Fortnite')
  await user.click(within(epic).getByRole('button', { name: 'Import' }))
  const gogLink = within(card('GOG')).getByRole('button', { name: 'Link account' })
  await user.click(gogLink)
  const token = within(card('GOG')).getByLabelText(/GOG refresh token/)
  await user.click(token)
  await act(async () => finish())
  expect(await within(epic).findByText(/Imported 1 titles/)).toBeInTheDocument()
  await act(() => new Promise((resolve) => setTimeout(resolve, 20)))
  expect(token).toHaveFocus()
})

test('a click elsewhere on the page during a sync is not undone by the next poll', async () => {
  const user = userEvent.setup()
  let running = false
  stubFetch((url: string, init: any) => {
    if (url.endsWith('/sync') && init?.method === 'POST') {
      running = true
      return new Promise(() => {})
    }
    return jsonResponse(
      connectionsBody([
        connection('gog', {
          state: running ? 'syncing' : 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'member', household_available: false },
          actions: running ? ['cancel'] : ['sync', 'reconnect', 'import_csv', 'disconnect'],
          last_sync: running ? job({ status: 'running', finished_at: null }) : job(),
        }),
      ]),
    )
  })
  render(<StoreConnections pollMs={20} />)
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  within(gog).getByRole('button', { name: 'Sync now' }).focus()
  await user.keyboard('{Enter}')
  await waitFor(
    () => expect(within(gog).getByRole('button', { name: 'Stop sync' })).toHaveFocus(),
    FOCUS_WAIT,
  )
  await user.click(screen.getByRole('heading', { name: 'Keep in sync' }))
  await act(() => new Promise((resolve) => setTimeout(resolve, 120)))
  expect(document.activeElement).toBe(document.body)
})

test('an Amazon sign-in missing only its device serial is repaired with the serial alone', async () => {
  const user = userEvent.setup()
  const fetchMock = stubFetch((url: string, init: any) => {
    if (url === '/api/ownership/amazon' && init?.method === 'POST')
      return jsonResponse({ ok: true, account: { store: 'amazon' } }, { status: 201 })
    return jsonResponse(
      connectionsBody([
        connection('amazon', {
          name: 'Amazon Games',
          state: 'reauth_required',
          account: {
            connected: true,
            linked_at: null,
            updated_at: null,
            external_account_id: null,
          },
          credential: { source: 'member', household_available: false },
          actions: ['reconnect', 'import_csv', 'disconnect'],
          last_sync: job({
            store: 'amazon',
            status: 'failed',
            outcome: {
              reason: 'device_serial_missing',
              message: 'Amazon needs the device serial from the sign-in. Reconnect and include it.',
              action: 'reconnect',
              retryable: false,
              audience: 'member',
            },
          }),
        }),
      ]),
    )
  })
  render(<StoreConnections />)
  const amazon = await screen.findByRole('listitem', { name: 'Amazon Games' })
  await user.click(within(amazon).getByRole('button', { name: 'Reconnect' }))
  expect(within(amazon).getByLabelText(/Nile \/ Heroic user.json/)).not.toBeRequired()
  await user.type(within(amazon).getByLabelText(/Device serial/), 'SERIAL-1')
  await user.click(within(amazon).getByRole('button', { name: 'Save link' }))
  const post = fetchMock.mock.calls.find(
    ([url, init]: any) => url === '/api/ownership/amazon' && init?.method === 'POST',
  )
  expect(JSON.parse(post![1].body)).toEqual({ device_serial: 'SERIAL-1' })
})

test('a sign-in of unknown origin says it may be the household one; Steam links without a server key', async () => {
  stubFetch(() =>
    jsonResponse(
      connectionsBody([
        connection('gog', {
          state: 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'unknown', household_available: true },
          actions: ['sync', 'reconnect', 'import_csv', 'disconnect'],
        }),
        connection('steam', {
          state: 'not_configured',
          setup: { ready: false, missing: 'server_key' },
          actions: ['connect', 'import_csv'],
        }),
      ]),
    ),
  )
  render(<StoreConnections />)
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  expect(within(gog).getByText(/may be the household sign-in/)).toBeInTheDocument()
  const steam = card('Steam')
  expect(within(steam).getByRole('button', { name: 'Link account' })).toBeInTheDocument()
  expect(
    within(steam).getByText(/Saving your Steam ID still lets a free-game claim/),
  ).toBeInTheDocument()
})

/**
 * Chrome clears focus to <body> a task after the focused button is disabled;
 * jsdom never does, and its blur() ignores a disabled element. Reproduce it:
 * call once React has committed the disabled render. Returns whether focus
 * really fell, so a test can prove it reached the path it is named for.
 */
function chromeBlursDisabledFocus() {
  const active = document.activeElement as HTMLElement | null
  if (!active || active === document.body || !active.matches(':disabled')) return false
  active.removeAttribute('disabled')
  active.blur()
  active.setAttribute('disabled', '')
  return document.activeElement === document.body
}

function linked(provider: string, running: boolean, overrides: Record<string, unknown> = {}) {
  const cancellable = provider !== 'steam'
  return connection(provider, {
    state: running ? 'syncing' : 'connected',
    cancellable,
    account: { connected: true, linked_at: null, updated_at: null },
    credential: {
      source: provider === 'steam' ? 'not_required' : 'member',
      household_available: false,
    },
    actions: running
      ? cancellable
        ? ['cancel']
        : []
      : ['sync', 'reconnect', 'import_csv', 'disconnect'],
    last_sync: running
      ? job({ store: provider, status: 'running', finished_at: null, cancellable })
      : job({ store: provider }),
    ...overrides,
  })
}

test('a card the member left never takes focus back from the card they moved to', async () => {
  const user = userEvent.setup()
  const running = new Set<string>()
  stubFetch((url: string, init: any) => {
    const sync = url.match(/^\/api\/ownership\/(\w+)\/sync$/)
    if (sync && init?.method === 'POST') {
      running.add(sync[1])
      return new Promise(() => {})
    }
    return jsonResponse(
      connectionsBody([linked('steam', running.has('steam')), linked('gog', running.has('gog'))]),
    )
  })
  render(<StoreConnections pollMs={20} />)
  const steam = await screen.findByRole('listitem', { name: 'Steam' })
  const gog = card('GOG')
  within(steam).getByRole('button', { name: 'Sync now' }).focus()
  await user.keyboard('{Enter}')
  expect(chromeBlursDisabledFocus()).toBe(true)
  // From <body>, the member moves on to GOG and syncs it too.
  within(gog).getByRole('button', { name: 'Sync now' }).focus()
  await user.keyboard('{Enter}')
  // (GOG's Sync may already have given way to Stop; either way focus falls
  // to <body> once, and only GOG may take it.)
  chromeBlursDisabledFocus()
  await waitFor(
    () => expect(within(gog).getByRole('button', { name: 'Stop sync' })).toHaveFocus(),
    FOCUS_WAIT,
  )
  await act(() => new Promise((resolve) => setTimeout(resolve, 80)))
  expect(gog.contains(document.activeElement)).toBe(true)
})

test('a failed save keeps focus in its form, even when polls land while it runs', async () => {
  const user = userEvent.setup()
  let fail: () => void = () => {}
  const fetchMock = stubFetch((url: string, init: any) => {
    if (url === '/api/ownership/gog' && init?.method === 'POST') {
      return new Promise((resolve) => {
        fail = () =>
          resolve(
            jsonResponse(
              { ok: false, error: 'Bad token', error_code: 'bad_request' },
              { ok: false, status: 400 },
            ),
          )
      })
    }
    // Steam is syncing, so the list re-reads (and every card re-renders) while the save runs.
    return jsonResponse(connectionsBody([linked('steam', true), linked('gog', false)]))
  })
  render(<StoreConnections pollMs={20} />)
  const gog = await screen.findByRole('listitem', { name: 'GOG' })
  await user.click(within(gog).getByRole('button', { name: 'Reconnect' }))
  await user.type(within(gog).getByLabelText(/GOG refresh token/), 'tok')
  within(gog).getByRole('button', { name: 'Save link' }).focus()
  await user.keyboard('{Enter}')
  expect(chromeBlursDisabledFocus()).toBe(true)
  // Polls while the save runs park focus on the card, not on the form's Close.
  await waitFor(
    () => expect(within(gog).getByRole('heading', { name: 'GOG' })).toHaveFocus(),
    FOCUS_WAIT,
  )
  await act(async () => fail())
  expect(await within(gog).findByRole('alert')).toHaveTextContent('Bad token')
  await waitFor(
    () => expect(within(gog).getByRole('button', { name: 'Save link' })).toHaveFocus(),
    FOCUS_WAIT,
  )
  expect(fetchMock.mock.calls.some(([url]: any) => String(url).endsWith('/gog/sync'))).toBe(false)
})

test('a sync that cannot be stopped parks focus on the heading, then returns it to Sync now', async () => {
  let running = false
  let finish: () => void = () => {}
  stubFetch((url: string, init: any) => {
    if (url.endsWith('/sync') && init?.method === 'POST') {
      running = true
      return new Promise((resolve) => {
        finish = () => {
          running = false
          resolve(jsonResponse({ ok: true, synced: 1, matched: 0, job: job({ store: 'steam' }) }))
        }
      })
    }
    return jsonResponse(connectionsBody([linked('gog', false), linked('steam', running)]))
  })
  const user = userEvent.setup()
  render(<StoreConnections pollMs={20} />)
  const steam = await screen.findByRole('listitem', { name: 'Steam' })
  within(steam).getByRole('button', { name: 'Sync now' }).focus()
  await user.keyboard('{Enter}')
  await waitFor(
    () => expect(within(steam).getByRole('heading', { name: 'Steam' })).toHaveFocus(),
    FOCUS_WAIT,
  )
  await act(async () => finish())
  await waitFor(
    () => expect(within(steam).getByRole('button', { name: 'Sync now' })).toHaveFocus(),
    FOCUS_WAIT,
  )
})

test('a heading the member focused themselves stays focused through polls', async () => {
  const user = userEvent.setup()
  stubFetch(() => jsonResponse(connectionsBody([linked('steam', true), linked('gog', false)])))
  render(<StoreConnections pollMs={20} />)
  const heading = within(await screen.findByRole('listitem', { name: 'GOG' })).getByRole(
    'heading',
    { name: 'GOG' },
  )
  await user.click(heading)
  expect(heading).toHaveFocus()
  await act(() => new Promise((resolve) => setTimeout(resolve, 100)))
  expect(heading).toHaveFocus()
})

test('arrows from a card heading step to its neighbours, and stop at the ends of the list', async () => {
  const user = userEvent.setup()
  stubFetch(() => jsonResponse(connectionsBody([linked('gog', false), linked('epic', false)])))
  render(<StoreConnections />)
  const epic = await screen.findByRole('listitem', { name: 'Epic Games' })
  const epicHeading = within(epic).getByRole('heading', { name: 'Epic Games' })
  epicHeading.focus()
  await user.keyboard('{ArrowDown}')
  expect(within(epic).getByRole('button', { name: 'Sync now' })).toHaveFocus()
  epicHeading.focus()
  await user.keyboard('{ArrowUp}')
  expect(within(card('GOG')).getByRole('button', { name: 'Disconnect' })).toHaveFocus()
  // Nothing above the first card's heading: Up leaves focus where it is.
  const gogHeading = within(card('GOG')).getByRole('heading', { name: 'GOG' })
  gogHeading.focus()
  expect(fireEvent.keyDown(gogHeading, { key: 'ArrowUp' })).toBe(true)
  expect(gogHeading).toHaveFocus()
})

test('Sync all stores runs every linked store and reports a failing one without hiding the rest', async () => {
  const user = userEvent.setup()
  const fetchMock = stubFetch((url: string) => {
    if (url === '/api/ownership/sync-all')
      return jsonResponse({
        ok: true,
        results: [
          { store: 'gog', status: 'succeeded', reason: null, synced: 4, matched: 1 },
          { store: 'epic', status: 'failed', reason: 'credential_rejected' },
          { store: 'steam', status: 'skipped', reason: 'not_connected' },
        ],
      })
    return jsonResponse(
      connectionsBody([
        connection('gog', {
          state: 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          actions: ['sync', 'reconnect', 'import_csv', 'disconnect'],
          last_sync: job(),
        }),
      ]),
    )
  })
  render(<StoreConnections />)
  await user.click(await screen.findByRole('button', { name: 'Sync all stores' }))
  expect(
    await screen.findByText(/Synced 1 of 2 stores \(4 titles\)\. Check epic\./),
  ).toBeInTheDocument()
  expect(fetchMock.mock.calls.some((c) => c[0] === '/api/ownership/sync-all')).toBe(true)
})

test('a launcher export is imported through the launcher route with its own name', async () => {
  const user = userEvent.setup()
  const fetchMock = stubFetch((url: string) => {
    if (url === '/api/imports/launcher')
      return jsonResponse({ ok: true, launcher: 'heroic', imported: 2, updated: 0 })
    return jsonResponse(
      connectionsBody([
        connection('heroic', { state: 'import_only', live: false, actions: ['import_file'] }),
      ]),
    )
  })
  render(<StoreConnections />)
  const heroic = await screen.findByRole('listitem', { name: 'Heroic' })
  expect(within(heroic).getByText(/Import a Heroic library export/)).toBeInTheDocument()
  await user.click(within(heroic).getByRole('button', { name: 'Import Heroic export' }))
  const file = new File(['{"library":[]}'], 'legendary_library.json', { type: 'application/json' })
  await user.upload(within(heroic).getByLabelText(/Heroic export/), file)
  await user.click(within(heroic).getByRole('button', { name: 'Import' }))
  expect(await within(heroic).findByText(/Imported 2 titles/)).toBeInTheDocument()
  const call = fetchMock.mock.calls.find((c) => c[0] === '/api/imports/launcher')
  expect((call?.[1].body as FormData).get('launcher')).toBe('heroic')
})
