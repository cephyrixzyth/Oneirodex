import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { showToast } from '../utils/toast'
import { GameCard } from './GameCard'

vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))

// The tile menu links out to the report form, so the card now needs a router
// the way every other surface rendering it already has one. Rendering it bare
// fails on `useContext(...)` being null, which reads as a card bug rather than
// a missing test wrapper.
function renderCard(ui: any) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

const game = {
  uuid: '11111111-1111-4111-8111-111111111111',
  name: 'Archery Kings VR',
  cover_url: '/static/library/images/cover.jpg',
  is_favorite: false,
  user_status: null,
  has_local_override: false,
  is_vr: false,
  genres: ['Sports'],
}

function jsonResponse(body: any) {
  const payload = JSON.stringify(body)
  return Promise.resolve({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(payload),
  })
}

function failedJsonResponse(body: any, status = 500) {
  const payload = JSON.stringify(body)
  return Promise.resolve({
    ok: false,
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
  document.head.innerHTML = '<meta name="csrf-token" content="test-csrf">'
  vi.clearAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('favorite toggle posts with CSRF and updates the card', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(() => jsonResponse({ success: true, is_favorite: true }))
  vi.stubGlobal('fetch', fetchMock)

  renderCard(<GameCard game={game} />)
  const favorite = screen.getByRole('button', { name: /add archery kings vr to favorites/i })
  await user.click(favorite)

  await waitFor(() => expect(favorite).toHaveAttribute('aria-pressed', 'true'))
  expect(fetchMock).toHaveBeenCalledWith(
    `/api/toggle_favorite/${game.uuid}`,
    expect.objectContaining({ method: 'POST' }),
  )
  const favoriteCall = (fetchMock.mock.calls as any[][]).find(([url]) =>
    String(url).includes('/api/toggle_favorite/'),
  )
  expect(requestHeaders(favoriteCall).get('Content-Type')).toBe('application/json')
  expect(requestHeaders(favoriteCall).get('X-CSRFToken')).toBe('test-csrf')
})

test('status selection posts with CSRF and updates the status button', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(() =>
    jsonResponse({ success: true, status: 'completed', message: 'Status updated' }),
  )
  vi.stubGlobal('fetch', fetchMock)

  renderCard(<GameCard game={game} showPlayStatus />)
  await user.click(screen.getByRole('button', { name: /game status: no status/i }))
  await user.click(screen.getByRole('button', { name: 'Completed' }))

  await waitFor(() =>
    expect(screen.getByRole('button', { name: /game status: completed/i })).toBeInTheDocument(),
  )
  expect(fetchMock).toHaveBeenCalledWith(
    `/api/set_game_status/${game.uuid}`,
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ status: 'completed' }),
    }),
  )
  const statusCall = (fetchMock.mock.calls as any[][]).find(([url]) =>
    String(url).includes('/api/set_game_status/'),
  )
  expect(requestHeaders(statusCall).get('X-CSRFToken')).toBe('test-csrf')
})

test('favorite write failure keeps the current state and shows feedback', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(() => failedJsonResponse({ error: 'Internal error', error_code: 'internal' }))
  vi.stubGlobal('fetch', fetchMock)

  renderCard(<GameCard game={{ ...game, is_favorite: true }} />)
  const favorite = screen.getByRole('button', { name: /remove archery kings vr from favorites/i })
  await user.click(favorite)

  await waitFor(() =>
    expect(showToast).toHaveBeenCalledWith('Could not update favorite. Please try again.', 'error'),
  )
  expect(favorite).toHaveAttribute('aria-pressed', 'true')
  expect(favorite).toBeEnabled()
})

test('status write failure keeps the current status and shows feedback', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(() => failedJsonResponse({ error: 'Internal error', error_code: 'internal' }))
  vi.stubGlobal('fetch', fetchMock)

  renderCard(<GameCard game={game} showPlayStatus />)
  await user.click(screen.getByRole('button', { name: /game status: no status/i }))
  await user.click(screen.getByRole('button', { name: 'Beaten', exact: true }))

  await waitFor(() =>
    expect(showToast).toHaveBeenCalledWith('Could not update game status. Please try again.', 'error'),
  )
  expect(screen.getByRole('button', { name: /game status: no status/i })).toBeInTheDocument()
})

test('popup exposes navigation actions and gates admin actions', async () => {
  const user = userEvent.setup()
  const { rerender } = renderCard(<GameCard game={game} isAdmin={false} />)

  await user.click(screen.getByRole('button', { name: /open actions for archery kings vr/i }))
  expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Edit Details' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Remove Game from DB' })).toBeNull()
  await user.click(screen.getByRole('button', { name: /open actions for archery kings vr/i }))

  // `rerender` replaces the whole tree, so the router has to come with it —
  // passing the card alone drops the context its menu link needs.
  rerender(
    <MemoryRouter>
      <GameCard game={game} isAdmin enableDeleteOnDisk />
    </MemoryRouter>,
  )
  await user.click(screen.getByRole('button', { name: /open actions for archery kings vr/i }))
  expect(screen.getByRole('link', { name: 'Edit Details' })).toHaveAttribute(
    'href',
    `/game_edit/${game.uuid}`,
  )
  expect(screen.getByRole('link', { name: 'Edit Images' })).toHaveAttribute(
    'href',
    `/edit_game_images/${game.uuid}`,
  )
  expect(screen.getByRole('button', { name: 'Refresh Images' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Remove Game from DB' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Delete Game on disk' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Move Library' })).toBeInTheDocument()
})

test('keyboard order puts Preview before the opened action menu contents', async () => {
  const user = userEvent.setup()
  renderCard(<GameCard game={game} isAdmin />)

  await user.click(screen.getByRole('button', { name: /open actions for archery kings vr/i }))
  await user.tab()
  expect(document.activeElement).toBe(
    screen.getByRole('button', { name: /preview archery kings vr/i }),
  )

  await user.tab()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Download' }))
})

test('popup ignores javascript: IGDB urls', async () => {
  const user = userEvent.setup()
  renderCard(<GameCard game={{ ...game, url: 'javascript:alert(1)' }} isAdmin={false} />)
  await user.click(screen.getByRole('button', { name: /open actions for archery kings vr/i }))
  expect(screen.queryByRole('link', { name: 'Open catalog page' })).toBeNull()
})
