import { vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { searchGames } from '../api/collections'
import { fetchPaletteSuggest } from '../api/palette'
import { openPreferencesModal } from '../api/preferences'
import { RECENT_TITLES_KEY } from '../utils/recentTitles'
import {
  buildPaletteCommands,
  CommandPalette,
  isLibrarySearchRoute,
  typeToSearchKey,
} from './CommandPalette'
import { ShellHarness } from '../testShell'

const navigateMock = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateMock,
  }
})

vi.mock('../api/preferences', async () => {
  const actual = await vi.importActual('../api/preferences')
  return {
    ...actual,
    openPreferencesModal: vi.fn(() => Promise.resolve()),
  }
})

vi.mock('../api/collections', async () => {
  const actual = await vi.importActual('../api/collections')
  return {
    ...actual,
    searchGames: vi.fn(() => Promise.resolve([])),
  }
})

vi.mock('../api/palette', () => ({
  fetchPaletteSuggest: vi.fn(() => Promise.resolve({ recent: [], popular: [] })),
}))

function renderPalette(shellConfig = {}, props = {}, initialEntries = ['/library']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <ShellHarness shell={shellConfig}>
        <CommandPalette {...props} />
      </ShellHarness>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  window.localStorage.removeItem(RECENT_TITLES_KEY)
  navigateMock.mockReset()
  vi.mocked(openPreferencesModal).mockClear()
  vi.mocked(searchGames).mockReset()
  vi.mocked(searchGames).mockResolvedValue([])
  vi.mocked(fetchPaletteSuggest).mockReset()
  vi.mocked(fetchPaletteSuggest).mockResolvedValue({ recent: [], popular: [] })
})

test('isLibrarySearchRoute matches library paths', () => {
  expect(isLibrarySearchRoute('/library')).toBe(true)
  expect(isLibrarySearchRoute('/library/')).toBe(true)
  expect(isLibrarySearchRoute('/discover')).toBe(false)
  expect(isLibrarySearchRoute('/game_details/abc')).toBe(false)
})

test('buildPaletteCommands includes primary, more, and preferences', () => {
  const ids = buildPaletteCommands({
    isAdmin: true,
    showHelp: true,
    showTrailers: true,
    enableVr: true,
  }).map((c) => c.id)

  expect(ids).toContain('library')
  expect(ids).toContain('discover')
  expect(ids).toContain('systems')
  expect(ids).toContain('chat')
  expect(ids).toContain('friends')
  expect(ids).toContain('big-picture')
  expect(ids).toContain('admin')
  expect(ids).toContain('help')
  expect(ids).toContain('preferences')
  expect(new Set(ids).size).toBe(ids.length)
})

test('hides admin and help when flags are off', () => {
  const ids = buildPaletteCommands({ isAdmin: false, showHelp: false }).map((c) => c.id)
  expect(ids).not.toContain('admin')
  expect(ids).not.toContain('help')
})

test('opens with Ctrl+K and closes with Escape', async () => {
  const user = userEvent.setup()
  renderPalette({ isAdmin: false }, {}, ['/discover'])

  expect(screen.queryByPlaceholderText(/search titles or pages/i)).toBeNull()

  await user.keyboard('{Control>}k{/Control}')
  expect(screen.getByPlaceholderText(/search titles or pages/i)).toBeInTheDocument()

  await user.keyboard('{Escape}')
  expect(screen.queryByPlaceholderText(/search titles or pages/i)).toBeNull()
})

test('on Library route uses Search library placeholder', async () => {
  const user = userEvent.setup()
  renderPalette({}, {})

  await user.keyboard('{Control>}k{/Control}')
  expect(screen.getByPlaceholderText(/search library/i)).toBeInTheDocument()
})

test('opens when open prop is true and filters by typeahead', async () => {
  const user = userEvent.setup()
  renderPalette({ isAdmin: true, showHelp: true }, { open: true }, ['/discover'])

  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByText('Game Catalog')).toBeInTheDocument()
  expect(within(dialog).getByText('Discover')).toBeInTheDocument()

  await user.type(screen.getByPlaceholderText(/search titles or pages/i), 'chat')
  expect(within(dialog).getByText('Chat')).toBeInTheDocument()
  expect(within(dialog).queryByText('Game Catalog')).toBeNull()
})

test('Library mode searches titles via /api/search and navigates to details', async () => {
  const user = userEvent.setup()
  vi.mocked(searchGames).mockResolvedValue([
    { uuid: 'game-1', name: 'Celeste' },
    { uuid: 'game-2', name: 'Celeste Classic' },
  ])

  renderPalette({}, { open: true })

  await user.type(screen.getByPlaceholderText(/search library/i), 'cel')

  await waitFor(() => {
    expect(searchGames).toHaveBeenCalled()
  })
  expect(vi.mocked(searchGames).mock.calls.at(-1)![0]).toBe('cel')

  const dialog = screen.getByRole('dialog')
  expect(await within(dialog).findByText('Celeste')).toBeInTheDocument()
  expect(within(dialog).getByText('Search library')).toBeInTheDocument()
  expect(within(dialog).getByText('Navigate')).toBeInTheDocument()

  await user.click(within(dialog).getByText('Celeste'))
  expect(navigateMock).toHaveBeenCalledWith('/game_details/game-1')
})

test('empty palette shows recent titles and household favourites', async () => {
  vi.mocked(fetchPaletteSuggest).mockResolvedValue({
    recent: [{ uuid: 'r1', name: 'Hades', hint: 'Played recently' }],
    popular: [{ uuid: 'p1', name: 'Celeste', hint: 'Favorited here' }],
  })
  renderPalette({}, { open: true }, ['/discover'])

  const dialog = await screen.findByRole('dialog')
  expect(await within(dialog).findByText('Hades')).toBeInTheDocument()
  expect(within(dialog).getByText('Played recently')).toBeInTheDocument()
  expect(within(dialog).getAllByText('Celeste').length).toBeGreaterThanOrEqual(1)
  expect(within(dialog).getByText('Favorited here')).toBeInTheDocument()
  expect(within(dialog).getByText('Recent titles')).toBeInTheDocument()
  expect(within(dialog).getByText('Popular here')).toBeInTheDocument()
})

test('does not show legacy titles when suggestions fail and keeps title search usable', async () => {
  const user = userEvent.setup()
  window.localStorage.setItem(
    RECENT_TITLES_KEY,
    JSON.stringify([{ uuid: 'private-1', name: 'Private prior account title' }]),
  )
  vi.mocked(fetchPaletteSuggest).mockRejectedValue(new Error('suggestions unavailable'))
  vi.mocked(searchGames).mockResolvedValue([{ uuid: 'allowed-1', name: 'Celeste' }])

  renderPalette({}, { open: true }, ['/discover'])

  const dialog = await screen.findByRole('dialog')
  expect(await within(dialog).findByRole('status')).toHaveTextContent(/suggestions are unavailable/i)
  expect(within(dialog).queryByText('Private prior account title')).toBeNull()
  expect(window.localStorage.getItem(RECENT_TITLES_KEY)).toBeNull()

  await user.type(within(dialog).getByPlaceholderText(/search titles or pages/i), 'cel')
  expect(await within(dialog).findByText('Celeste')).toBeInTheDocument()
})

test('discards suggestions from a prior viewer after an identity change', async () => {
  let resolvePrior: (value: any) => void = () => undefined
  const priorResponse = new Promise((resolve) => {
    resolvePrior = resolve
  })
  vi.mocked(fetchPaletteSuggest)
    .mockReturnValueOnce(priorResponse as any)
    .mockResolvedValueOnce({
      recent: [{ uuid: 'current-1', name: 'Current viewer title' }],
      popular: [],
    })

  const renderForViewer = (userId: number) => (
    <MemoryRouter initialEntries={['/discover']}>
      <ShellHarness shell={{ userId }}>
        <CommandPalette open />
      </ShellHarness>
    </MemoryRouter>
  )
  const view = render(renderForViewer(1))

  await waitFor(() => expect(fetchPaletteSuggest).toHaveBeenCalledTimes(1))
  view.rerender(renderForViewer(2))
  expect(await screen.findByText('Current viewer title')).toBeInTheDocument()

  resolvePrior({ recent: [{ uuid: 'prior-1', name: 'Prior viewer title' }], popular: [] })
  await waitFor(() => expect(screen.queryByText('Prior viewer title')).toBeNull())
  expect(screen.getByText('Current viewer title')).toBeInTheDocument()
})

test('title search runs from Discover, not only Game Catalog', async () => {
  vi.mocked(searchGames).mockResolvedValue([{ uuid: 'game-9', name: 'Outer Wilds' }])
  const user = userEvent.setup()
  renderPalette({}, { open: true }, ['/discover'])

  await user.type(screen.getByPlaceholderText(/search titles or pages/i), 'out')
  await waitFor(() => {
    expect(searchGames).toHaveBeenCalled()
  })
  expect(vi.mocked(searchGames).mock.calls.at(-1)![0]).toBe('out')
  expect(await screen.findByText('Outer Wilds')).toBeInTheDocument()
})

test('selecting a nav command navigates via useNavigate', async () => {
  const user = userEvent.setup()
  renderPalette({}, { open: true }, ['/discover'])

  await user.click(screen.getByText('Systems'))
  expect(navigateMock).toHaveBeenCalledWith('/systems')
})

test('friends command opens dock event instead of navigating', async () => {
  const user = userEvent.setup()
  const onOpen = vi.fn()
  window.addEventListener('od-open-social-companion', onOpen)
  try {
    const friends = buildPaletteCommands({}).find((c) => c.id === 'friends')
    expect(friends.action).toBe('open-friends')
    expect(friends.to).toBeUndefined()

    renderPalette({}, { open: true }, ['/discover'])
    await user.click(screen.getByText('Friends'))
    expect(onOpen).toHaveBeenCalledTimes(1)
    expect(navigateMock).not.toHaveBeenCalled()
  } finally {
    window.removeEventListener('od-open-social-companion', onOpen)
  }
})

test('chat command opens slide-out event instead of navigating', async () => {
  const user = userEvent.setup()
  const onOpen = vi.fn()
  window.addEventListener('od-open-chat-panel', onOpen)
  try {
    const chat = buildPaletteCommands({}).find((c) => c.id === 'chat')
    expect(chat.action).toBe('open-chat')
    expect(chat.to).toBeUndefined()

    renderPalette({}, { open: true }, ['/discover'])
    await user.click(screen.getByText('Chat'))
    expect(onOpen).toHaveBeenCalledTimes(1)
    expect(navigateMock).not.toHaveBeenCalled()
  } finally {
    window.removeEventListener('od-open-chat-panel', onOpen)
  }
})

test('preferences command opens preferences modal', async () => {
  const user = userEvent.setup()
  renderPalette({}, { open: true }, ['/discover'])

  await user.click(screen.getByText('Preferences'))
  expect(openPreferencesModal).toHaveBeenCalled()
})

test('admin external command uses location href', async () => {
  const user = userEvent.setup()
  const loc = { href: '/library' }
  vi.stubGlobal('location', loc)

  renderPalette({ isAdmin: true }, { open: true }, ['/discover'])
  await user.click(screen.getByText('Admin'))
  expect(loc.href).toBe('/admin/dashboard')

  vi.unstubAllGlobals()
})

describe('type-to-search', () => {
  const key = (k: any, extra = {}) => ({ key: k, target: document.body, ...extra })

  test('a printable key opens the palette and seeds it', () => {
    expect(typeToSearchKey(key('a'))).toBe(true)
    expect(typeToSearchKey(key('7'))).toBe(true)
    // Shift is not a chord — Shift+A is just "A".
    expect(typeToSearchKey(key('A', { shiftKey: true }))).toBe(true)
  })

  test('shortcuts and navigation keys are left alone', () => {
    // Ctrl+C must stay copy; Enter/Tab/Escape/arrows must keep working.
    expect(typeToSearchKey(key('c', { ctrlKey: true }))).toBe(false)
    expect(typeToSearchKey(key('c', { metaKey: true }))).toBe(false)
    expect(typeToSearchKey(key('c', { altKey: true }))).toBe(false)
    for (const k of ['Enter', 'Tab', 'Escape', 'ArrowDown', 'F5', 'Backspace']) {
      expect(typeToSearchKey(key(k))).toBe(false)
    }
    // Space scrolls; a palette that opens on scroll is unusable.
    expect(typeToSearchKey(key(' '))).toBe(false)
  })

  test('typing into a field is never hijacked', () => {
    // Without this the filter box and the chat composer would lose focus
    // mid-word to a palette the reader did not ask for.
    for (const tag of ['input', 'textarea', 'select']) {
      const el = document.createElement(tag)
      document.body.appendChild(el)
      expect(typeToSearchKey(key('a', { target: el }))).toBe(false)
      el.remove()
    }
    const rich = document.createElement('div')
    rich.setAttribute('contenteditable', 'true')
    document.body.appendChild(rich)
    expect(typeToSearchKey(key('a', { target: rich }))).toBe(false)
    rich.remove()
  })
})
