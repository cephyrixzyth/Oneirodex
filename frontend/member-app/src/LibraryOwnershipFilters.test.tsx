import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { LibraryApp } from './LibraryApp'
import { ShellHarness } from './testShell'
import { jsonResponse, stubFetch } from './testJsonResponse'

const CONFIG = {
  perPage: 20,
  showPlayStatus: false,
  isAdmin: false,
  libraryCount: 1,
  gamesCount: 1,
}

function Location() {
  const location = useLocation()
  return <output data-testid="location">{location.search}</output>
}

function renderLibrary(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ShellHarness shell={{}}>
        <LibraryApp initialConfig={CONFIG} />
        <Location />
      </ShellHarness>
    </MemoryRouter>,
  )
}

function browseUrls(fetchMock: any): URLSearchParams[] {
  return fetchMock.mock.calls
    .map(([url]: any) => String(url))
    .filter((url: string) => url.startsWith('/browse_games?'))
    .map((url: string) => new URL(url, 'http://local').searchParams)
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = 'libraryFilters=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
})

function stubLibrary() {
  return stubFetch((url: string) => {
    if (url.startsWith('/browse_games?'))
      return jsonResponse({ games: [], pages: 1, current_page: 1, total: 0 })
    if (url.startsWith('/api/filters/bundle')) {
      return jsonResponse({
        libraries: [],
        genres: [
          { id: 1, name: 'RPG' },
          { id: 2, name: 'Puzzle' },
        ],
        ownershipStores: [
          { id: 'steam', name: 'Steam' },
          { id: 'gog', name: 'GOG' },
        ],
      })
    }
    return jsonResponse({ ok: true, sync_enabled: true, connections: [] })
  })
}

test('a deep link with store filters reaches browse', async () => {
  const fetchMock = stubLibrary()
  renderLibrary('/library?store=steam&ownership=owned')
  await waitFor(() => expect(browseUrls(fetchMock).length).toBeGreaterThan(0))
  const params = browseUrls(fetchMock).at(-1)!
  expect(params.get('store')).toBe('steam')
  expect(params.get('ownership')).toBe('owned')
})

/** Filters live in the context-bar popover (two-bar chrome is the default). */
async function filterButton(user: any, name: string) {
  if (!screen.queryByRole('dialog', { name: /Filters/ })) {
    await user.click(await screen.findByRole('button', { name: /^Filters/ }))
  }
  const dialog = await screen.findByRole('dialog', { name: /Filters/ })
  return within(dialog).findByRole('button', { name })
}

test('choosing ownership filters writes them to the URL for reloads and links', async () => {
  const user = userEvent.setup()
  const fetchMock = stubLibrary()
  renderLibrary('/library?genre=RPG')
  await user.click(await filterButton(user, 'Owned'))
  await waitFor(() =>
    expect(screen.getByTestId('location').textContent).toContain('ownership=owned'),
  )
  await user.click(await filterButton(user, 'GOG'))
  await waitFor(() =>
    expect(screen.getByTestId('location').textContent).toBe('?genre=RPG&ownership=owned&store=gog'),
  )
  await waitFor(() => expect(browseUrls(fetchMock).at(-1)!.get('store')).toBe('gog'))
  await user.click(await filterButton(user, 'All games'))
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('?genre=RPG'))
})

test('an ownership chip keeps a genre the member changed after a deep link', async () => {
  const user = userEvent.setup()
  const fetchMock = stubLibrary()
  renderLibrary('/library?genre=RPG')
  await filterButton(user, 'Owned')
  const dialog = screen.getByRole('dialog', { name: /Filters/ })
  await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Genre' }), 'Puzzle')
  await user.click(within(dialog).getByRole('button', { name: 'Apply' }))
  await waitFor(() => expect(browseUrls(fetchMock).at(-1)!.get('genre')).toBe('Puzzle'))
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('?genre=Puzzle'))

  await user.click(await filterButton(user, 'Owned'))
  await waitFor(() =>
    expect(screen.getByTestId('location').textContent).toBe('?genre=Puzzle&ownership=owned'),
  )
  await waitFor(() => expect(browseUrls(fetchMock).at(-1)!.get('ownership')).toBe('owned'))
  expect(browseUrls(fetchMock).at(-1)!.get('genre')).toBe('Puzzle')
})

test('clearing a search that came from the URL does not come back with the next filter', async () => {
  const user = userEvent.setup()
  const fetchMock = stubLibrary()
  renderLibrary('/library?q=zelda')
  await waitFor(() => expect(browseUrls(fetchMock).at(-1)?.get('name')).toBe('zelda'))
  await filterButton(user, 'Owned')
  await user.clear(
    within(screen.getByRole('dialog', { name: /Filters/ })).getByRole('searchbox', {
      name: 'Search library by title',
    }),
  )
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe(''))
  await user.click(await filterButton(user, 'Owned'))
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('?ownership=owned'))
  await waitFor(() => expect(browseUrls(fetchMock).at(-1)!.get('ownership')).toBe('owned'))
  expect(browseUrls(fetchMock).at(-1)!.has('name')).toBe(false)
})
