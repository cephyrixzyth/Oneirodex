import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { ManualIdentifyPage } from './ManualIdentifyPage'
import { confirmAction } from '@oneirodex/ui'

vi.mock('@oneirodex/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@oneirodex/ui')>()
  return { ...actual, confirmAction: vi.fn() }
})

const originalFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function response(body: unknown) {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

function LinkSuccessRoute() {
  const location = useLocation()
  const state = location.state as { linkSuccess?: string } | null
  return <div>Unmatched scan management {state?.linkSuccess || ''}</div>
}

test('loads options, applies an IGDB match, and posts a JSON identify payload', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'PC', platform_name: 'PC' }],
        taxonomies: {
          genres: [{ id: 7, name: 'Adventure' }],
          game_modes: [],
          themes: [],
          platforms: [],
          player_perspectives: [],
        },
        categories: [{ value: 'MAIN_GAME', label: 'Main Game' }],
        statuses: [{ value: 'RELEASED', label: 'Released' }],
      }) as any
    if (url.startsWith('/api/search_igdb_by_name?'))
      return response({
        results: [{ id: 123, name: 'Sample', summary: 'Summary', genres: [{ name: 'Adventure' }] }],
      }) as any
    return response({ redirect_url: '/libraries' }) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter
      initialEntries={['/add_game_manual?full_disk_path=%2Fgames%2FSample&library_uuid=lib-1']}
    >
      <ManualIdentifyPage />
    </MemoryRouter>,
  )

  fireEvent.change(await screen.findByLabelText('Game name'), { target: { value: 'Sample' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search IGDB' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Use this match' }))
  expect(screen.getByLabelText('Name')).toHaveValue('Sample')
  expect(screen.getByLabelText('Adventure')).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Save and identify game' }))

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/admin/manual-identify',
      expect.objectContaining({ method: 'POST' }),
    ),
  )
  const saveCall = fetchMock.mock.calls.find(
    ([url]) => String(url) === '/api/admin/manual-identify',
  )
  expect(JSON.parse((saveCall?.[1] as RequestInit).body as string)).toMatchObject({
    igdb_id: 123,
    name: 'Sample',
    library_uuid: 'lib-1',
    full_disk_path: '/games/Sample',
    genre_ids: [7],
  })
})

test('prefills identify fields from the existing direct-entry query contract', async () => {
  globalThis.fetch = vi.fn(async () =>
    response({
      libraries: [{ uuid: 'lib-1', name: 'PC', platform_name: 'PC' }],
      taxonomies: {
        genres: [],
        game_modes: [],
        themes: [],
        platforms: [],
        player_perspectives: [],
      },
      categories: [],
      statuses: [],
    }),
  ) as unknown as typeof fetch
  render(
    <MemoryRouter
      initialEntries={[
        '/add_game_manual?name=Sample&igdb_id=123&library_uuid=lib-1&full_disk_path=%2Fgames%2FSample',
      ]}
    >
      <ManualIdentifyPage />
    </MemoryRouter>,
  )
  expect(await screen.findByLabelText('Name')).toHaveValue('Sample')
  expect(screen.getByLabelText('Game name')).toHaveValue('Sample')
  expect(screen.getByLabelText('IGDB ID')).toHaveValue(123)
})

test.each([true, false])(
  'searches and confirms linking an existing game from edit page (from unmatched: %s)',
  async (fromUnmatched) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'PC', platform_name: 'PC' }],
        taxonomies: {
          genres: [],
          game_modes: [],
          themes: [],
          platforms: [],
          player_perspectives: [],
        },
        categories: [],
        statuses: [],
      }) as any
    if (url.endsWith('/api/admin/manual-identify/game-1'))
      return response({
        game: {
          uuid: 'game-1',
          name: 'Current Game',
          igdb_id: 123,
          library_uuid: 'lib-1',
          full_disk_path: '/games/current',
          provider_urls: {},
          genre_ids: [],
          game_mode_ids: [],
          theme_ids: [],
          platform_ids: [],
          player_perspective_ids: [],
        },
        scan_running: false,
      }) as any
    if (url.endsWith('/api/admin/games_search?q=Target'))
      return response([
        { uuid: 'target-1', name: 'Target Game', full_disk_path: '/games/target' },
      ]) as any
    return response({ ok: true }) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  vi.mocked(confirmAction).mockResolvedValue(true)
  render(
    <MemoryRouter
      initialEntries={[
        `/game_edit/game-1${fromUnmatched ? '?from_unmatched=true' : ''}`,
      ]}
    >
      <Routes>
        <Route path="/game_edit/:gameUuid" element={<ManualIdentifyPage />} />
        <Route path="/libraries" element={<div>Library page</div>} />
        <Route path="/scan_management" element={<LinkSuccessRoute />} />
      </Routes>
    </MemoryRouter>,
  )

  const search = await screen.findByLabelText('Search existing games')
  fireEvent.change(search, { target: { value: 'Target' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search existing games' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Target Game · /games/target' }))
  fireEvent.click(screen.getByRole('button', { name: 'Link selected game' }))

  await waitFor(() => expect(confirmAction).toHaveBeenCalled())
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/library_tools/link_existing_game',
      expect.objectContaining({ method: 'POST' }),
    ),
  )
  const linkCall = fetchMock.mock.calls.find(
    ([url]) => String(url) === '/api/library_tools/link_existing_game',
  )
  expect(JSON.parse((linkCall?.[1] as RequestInit).body as string)).toMatchObject({
    game_uuid: 'target-1',
    full_disk_path: '/games/current',
    library_uuid: 'lib-1',
    from_unmatched: fromUnmatched,
  })
  expect(
    await screen.findByText(
      "Unmatched scan management Linked existing game 'Target Game' to this folder.",
    ),
  ).toBeInTheDocument()
  },
)
