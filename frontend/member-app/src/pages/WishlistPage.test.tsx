import { vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WishlistPage } from './WishlistPage'
import { ShellHarness } from '../testShell'

function jsonResponse(body: any, { ok = true, status = 200 } = {}): any {
  const payload = JSON.stringify(body)
  return Promise.resolve({
    ok,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(payload),
  })
}

function requestHeaders(call: any) {
  return new Headers(call?.[1]?.headers)
}

beforeEach(() => {
  document.head.innerHTML = '<meta name="csrf-token" content="test-csrf-token">'
  global.fetch = vi.fn()
})

afterEach(() => {
  document.head.innerHTML = ''
  delete (global as any).fetch
})

test('renders requests returned by the API', async () => {
  vi.mocked(global.fetch).mockReturnValue(
    jsonResponse({
      requests: [
        {
          id: 1,
          title: 'Hollow Knight: Silksong',
          notes: 'Any edition works',
          status: 'pending',
          created_at: '2026-07-01T12:00:00+00:00',
          linked_game_uuid: null,
        },
      ],
    }),
  )

  render(
    <ShellHarness shell={{}}>
      <WishlistPage />
    </ShellHarness>,
  )

  expect(screen.getByRole('status', { busy: true })).toBeInTheDocument()
  expect(await screen.findByText('Hollow Knight: Silksong')).toBeInTheDocument()
  expect(screen.getByText('Any edition works')).toBeInTheDocument()
  expect(screen.getByText('pending')).toBeInTheDocument()
  expect(screen.getByText('Jul 1, 2026')).toBeInTheDocument()
  expect(global.fetch).toHaveBeenCalledWith(
    '/api/requests',
    expect.objectContaining({ credentials: 'include' }),
  )
})

test('shows empty state when there are no requests', async () => {
  vi.mocked(global.fetch).mockReturnValue(jsonResponse({ requests: [] }))

  render(
    <ShellHarness shell={{}}>
      <WishlistPage />
    </ShellHarness>,
  )

  expect(
    await screen.findByText(
      'No requests yet. Add a title above and your librarians will take a look.',
    ),
  ).toBeInTheDocument()
})

test('shows error state with retry', async () => {
  const user = userEvent.setup()
  vi.mocked(global.fetch)
    .mockReturnValueOnce(jsonResponse({ error: 'nope' }, { ok: false, status: 500 }))
    .mockReturnValue(jsonResponse({ requests: [] }))

  render(
    <ShellHarness shell={{}}>
      <WishlistPage />
    </ShellHarness>,
  )

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load wishlist.')
  await user.click(screen.getByRole('button', { name: /Try again/i }))

  expect(
    await screen.findByText(
      'No requests yet. Add a title above and your librarians will take a look.',
    ),
  ).toBeInTheDocument()
})

test('cancelling a pending request sends DELETE with the CSRF header', async () => {
  const user = userEvent.setup()
  vi.mocked(global.fetch)
    .mockReturnValueOnce(
      jsonResponse({
        requests: [
          { id: 42, title: 'Outer Wilds', notes: null, status: 'pending', created_at: null },
        ],
      }),
    )
    .mockReturnValueOnce(jsonResponse({ ok: true, id: 42 }))
    .mockReturnValue(jsonResponse({ requests: [] }))

  render(
    <ShellHarness shell={{}}>
      <WishlistPage />
    </ShellHarness>,
  )

  expect(await screen.findByText('Outer Wilds')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Cancel' }))

  await waitFor(() => {
    const del = vi
      .mocked(global.fetch)
      .mock.calls.find(
        (call: any) => call[0] === '/api/requests/42' && call[1]?.method === 'DELETE',
      )
    expect(del).toBeTruthy()
    expect(del![1]).toEqual(expect.objectContaining({ method: 'DELETE', credentials: 'include' }))
    expect(requestHeaders(del).get('X-CSRFToken')).toBe('test-csrf-token')
  })

  expect(
    await screen.findByText(
      'No requests yet. Add a title above and your librarians will take a look.',
    ),
  ).toBeInTheDocument()
})

test('librarian can resolve a request and toggle the all-requests view', async () => {
  const user = userEvent.setup()
  vi.mocked(global.fetch).mockReturnValue(
    jsonResponse({
      requests: [{ id: 7, title: 'Tunic', notes: null, status: 'pending', created_at: null }],
    }),
  )

  render(
    <ShellHarness shell={{ isLibrarian: true }}>
      <WishlistPage />
    </ShellHarness>,
  )

  expect(await screen.findByText('Tunic')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Fulfilled' }))

  await waitFor(() => {
    const patch = vi
      .mocked(global.fetch)
      .mock.calls.find((call: any) => call[0] === '/api/requests/7' && call[1]?.method === 'PATCH')
    expect(patch).toBeTruthy()
    expect(patch![1]).toEqual(
      expect.objectContaining({
        method: 'PATCH',
        credentials: 'include',
        body: JSON.stringify({ status: 'fulfilled' }),
      }),
    )
    expect(requestHeaders(patch).get('X-CSRFToken')).toBe('test-csrf-token')
    expect(requestHeaders(patch).get('Content-Type')).toBe('application/json')
  })

  await user.click(screen.getByRole('checkbox', { name: 'Show everyone’s requests' }))

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/requests?all=1',
      expect.objectContaining({ credentials: 'include' }),
    )
  })
})

test('surfaces a failed create request to the user', async () => {
  const user = userEvent.setup()
  vi.mocked(global.fetch)
    .mockReturnValueOnce(jsonResponse({ requests: [] }))
    .mockReturnValueOnce(
      jsonResponse(
        { error: 'Wishlist requests are not available for this account' },
        { ok: false, status: 403 },
      ),
    )

  render(
    <ShellHarness shell={{}}>
      <WishlistPage />
    </ShellHarness>,
  )

  await screen.findByText(
    'No requests yet. Add a title above and your librarians will take a look.',
  )
  await user.type(screen.getByLabelText('Title'), 'Blasphemous 2')
  await user.click(screen.getByRole('button', { name: 'Request' }))

  expect(
    await screen.findByText('Wishlist requests are not available for this account'),
  ).toBeInTheDocument()
})

test('explains when a whitespace-only title request is submitted', async () => {
  const user = userEvent.setup()
  vi.mocked(global.fetch).mockReturnValue(jsonResponse({ requests: [] }))

  render(
    <ShellHarness shell={{}}>
      <WishlistPage />
    </ShellHarness>,
  )

  await screen.findByText(
    'No requests yet. Add a title above and your librarians will take a look.',
  )
  await user.type(screen.getByLabelText('Title'), '   ')
  await user.click(screen.getByRole('button', { name: /^Request$/ }))

  expect(
    vi
      .mocked(global.fetch)
      .mock.calls.filter((call: any) => call[0] === '/api/requests' && call[1]?.method === 'POST'),
  ).toHaveLength(0)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Enter a title before sending your request.',
  )
})

test('new chrome moves the request form and the librarian toggle into bar two', async () => {
  const user = userEvent.setup()
  vi.mocked(global.fetch).mockReturnValue(jsonResponse({ requests: [] }))

  render(
    <ShellHarness shell={{ enableNewChrome: true, isLibrarian: true }}>
      <WishlistPage />
    </ShellHarness>,
  )
  await waitFor(() => expect(screen.queryByRole('status', { busy: true })).toBeNull())

  expect(screen.queryByRole('heading', { name: 'Wishlist' })).toBeNull()
  // A permanently open request form above the list is furniture, not an action.
  expect(screen.queryByPlaceholderText('Game title')).toBeNull()

  const request = screen.getByRole('button', { name: 'Request a title' })
  // Fused with My requests / Everyone’s — Library Apply/Clear shape, quiet
  // chrome (no permanent primary fill).
  expect(request.closest('.od-cbtn-group')).toBeTruthy()
  expect(request.className).not.toContain('od-cbtn--primary')
  expect(request.querySelector('svg')).toBeNull()

  await user.click(request)
  expect(screen.getByPlaceholderText('Game title')).toBeInTheDocument()
})

test('the librarian scope toggle stays a real toggle after the move', async () => {
  // It was a checkbox; as a bar-two button it must still report its state, or
  // a librarian cannot tell whose requests they are looking at.
  const user = userEvent.setup()
  vi.mocked(global.fetch).mockReturnValue(jsonResponse({ requests: [] }))

  render(
    <ShellHarness shell={{ enableNewChrome: true, isLibrarian: true }}>
      <WishlistPage />
    </ShellHarness>,
  )
  await waitFor(() => expect(screen.queryByRole('status', { busy: true })).toBeNull())

  const toggle = screen.getByRole('button', { name: /Everyone/ })
  expect(toggle).toHaveAttribute('aria-pressed', 'false')
  expect(toggle.closest('.od-cbtn-group')).toContainElement(
    screen.getByRole('button', { name: 'Request a title' }),
  )
  await user.click(toggle)
  expect(toggle).toHaveAttribute('aria-pressed', 'true')
})

test('members never see the librarian scope toggle', async () => {
  vi.mocked(global.fetch).mockReturnValue(jsonResponse({ requests: [] }))
  render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <WishlistPage />
    </ShellHarness>,
  )
  await waitFor(() => expect(screen.queryByRole('status', { busy: true })).toBeNull())
  expect(screen.queryByRole('button', { name: /Everyone/ })).toBeNull()
})
