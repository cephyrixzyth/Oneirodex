import { vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { BigPicturePage } from './BigPicturePage'
import * as browseApi from '../api/browse'
import * as downloadsApi from '../api/downloads'
import { ShellHarness } from '../testShell'

vi.mock('../api/browse', () => ({
  fetchBrowseGames: vi.fn(),
}))

vi.mock('../api/downloads', () => ({
  initiateGameDownload: vi.fn(),
}))

vi.mock('../api/clientCommands', () => ({
  queueClientCommand: vi.fn(),
}))

function renderPage(ui: any) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

beforeEach(() => {
  vi.mocked(browseApi.fetchBrowseGames).mockReset()
  vi.mocked(downloadsApi.initiateGameDownload).mockReset()
  vi.mocked(downloadsApi.initiateGameDownload).mockResolvedValue({})
})

const GAMES = [
  {
    uuid: 'a1',
    name: 'Alpha Game',
    cover_url: 'covers/alpha.jpg',
    summary: 'An alpha adventure.',
    size: '4.2 GB',
    owned: true,
  },
  {
    uuid: 'b2',
    name: 'Beta Game',
    cover_url: null,
    summary: 'A beta romp.',
  },
]

test('shows loading then renders tiles and hero for the first game', async () => {
  vi.mocked(browseApi.fetchBrowseGames).mockResolvedValue({ games: GAMES })

  renderPage(
    <ShellHarness shell={{}}>
      <BigPicturePage />
    </ShellHarness>,
  )

  expect(screen.getByText(/Loading games/)).toBeInTheDocument()

  const alphaTile = await screen.findByRole('option', { name: 'Alpha Game' })
  expect(alphaTile).toHaveAttribute('href', '/game_details/a1')
  expect(alphaTile).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('option', { name: 'Beta Game' })).toHaveAttribute(
    'href',
    '/game_details/b2',
  )

  expect(browseApi.fetchBrowseGames).toHaveBeenCalledWith(
    { per_page: 48, sort_by: 'date_identified', sort_order: 'desc' },
    expect.objectContaining({ signal: expect.anything() }),
  )

  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Alpha Game')
  expect(screen.getByText('An alpha adventure.')).toBeInTheDocument()
  expect(screen.getByText('OWNED · 4.2 GB')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/game_details/a1')
  expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument()
})

test('arrow keys move the selection and update the hero', async () => {
  const user = userEvent.setup()
  vi.mocked(browseApi.fetchBrowseGames).mockResolvedValue({ games: GAMES })

  renderPage(
    <ShellHarness shell={{}}>
      <BigPicturePage />
    </ShellHarness>,
  )

  const alphaTile = await screen.findByRole('option', { name: 'Alpha Game' })
  // The tile existing and the tile holding focus are two different moments.
  // Auto-focus happens in a passive `useEffect`, which React flushes after the
  // commit that `findByRole` is already satisfied by, so asserting focus
  // directly is a race — one this file lost only under a full run, where the
  // gap is wide enough to catch. The keyboard assertions below need no such
  // wait: `select()` focuses synchronously inside the event handler.
  await waitFor(() => expect(alphaTile).toHaveFocus())

  await user.keyboard('{ArrowRight}')

  const betaTile = screen.getByRole('option', { name: 'Beta Game' })
  expect(betaTile).toHaveAttribute('aria-selected', 'true')
  expect(betaTile).toHaveFocus()
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Beta Game')
  expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/game_details/b2')

  await user.keyboard('{ArrowLeft}')
  expect(screen.getByRole('option', { name: 'Alpha Game' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
})

test('shows empty state when the library has no games', async () => {
  vi.mocked(browseApi.fetchBrowseGames).mockResolvedValue({ games: [] })

  renderPage(
    <ShellHarness shell={{}}>
      <BigPicturePage />
    </ShellHarness>,
  )

  expect(await screen.findByText('No games in your library yet.')).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('No games')
  expect(screen.queryByRole('option')).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Open' })).not.toBeInTheDocument()
})

test('shows an error with retry that recovers', async () => {
  const user = userEvent.setup()
  vi.mocked(browseApi.fetchBrowseGames)
    .mockRejectedValueOnce(new Error('boom'))
    .mockResolvedValueOnce({ games: GAMES })

  renderPage(
    <ShellHarness shell={{}}>
      <BigPicturePage />
    </ShellHarness>,
  )

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load Big Picture.')

  await user.click(screen.getByRole('button', { name: 'Retry' }))

  expect(await screen.findByRole('option', { name: 'Alpha Game' })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('friends companion starts closed (SSE gated)', async () => {
  vi.mocked(browseApi.fetchBrowseGames).mockResolvedValue({ games: GAMES })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => ({ friends: [], friend_count: 0 }) })),
  )

  renderPage(
    <ShellHarness shell={{}}>
      <BigPicturePage />
    </ShellHarness>,
  )
  await screen.findByRole('option', { name: 'Alpha Game' })

  expect(screen.getByRole('button', { name: /open friends companion/i })).toBeInTheDocument()
  expect(screen.queryByLabelText(/^Friends companion$/i)).not.toBeInTheDocument()
})

describe('TC-3 honesty on the ten-foot screen', () => {
  afterEach(() => {
    try {
      sessionStorage.removeItem('oneirodex-seat')
    } catch {
      /* private mode */
    }
  })

  function asThinSeat() {
    sessionStorage.setItem('oneirodex-seat', 'thin')
  }

  test('a thin seat is not offered Download or Install', async () => {
    asThinSeat()
    vi.mocked(browseApi.fetchBrowseGames).mockResolvedValue({
      games: [{ ...GAMES[0], client_connected: true, lifecycle_state: 'downloaded' }],
      total: 1,
    })
    renderPage(
      <ShellHarness shell={{}}>
        <BigPicturePage />
      </ShellHarness>,
    )
    await screen.findByRole('heading', { name: 'Alpha Game' })
    // The buttons a thin token can never complete are simply absent, rather
    // than present and failing at the press.
    expect(screen.queryByRole('button', { name: 'Download' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Install' })).toBeNull()
    // What it can do is still there.
    expect(screen.getByRole('link', { name: 'Open' })).toBeTruthy()
  })

  test('a normal browser seat still gets both', async () => {
    vi.mocked(browseApi.fetchBrowseGames).mockResolvedValue({
      games: [{ ...GAMES[0], client_connected: true, lifecycle_state: 'downloaded' }],
      total: 1,
    })
    renderPage(
      <ShellHarness shell={{}}>
        <BigPicturePage />
      </ShellHarness>,
    )
    await screen.findByRole('heading', { name: 'Alpha Game' })
    expect(screen.getByRole('button', { name: 'Download' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Install' })).toBeTruthy()
  })

  test('the D shortcut does not navigate to a download on a thin seat', async () => {
    asThinSeat()
    vi.mocked(browseApi.fetchBrowseGames).mockResolvedValue({ games: [GAMES[0]], total: 1 })
    renderPage(
      <ShellHarness shell={{}}>
        <BigPicturePage />
      </ShellHarness>,
    )
    await screen.findByRole('heading', { name: 'Alpha Game' })
    const before = window.location.href
    await userEvent.keyboard('d')
    // jsdom would record an href assignment; the guard means there is none.
    expect(window.location.href).toBe(before)
  })
})
