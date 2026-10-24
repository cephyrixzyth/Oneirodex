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
const locationAssign = vi.fn()
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.unstubAllGlobals()
  locationAssign.mockReset()
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
  vi.stubGlobal('location', { ...window.location, assign: locationAssign })
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    return response({ redirect_url: '/library' }) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter
      initialEntries={[
        '/add_game_manual?full_disk_path=%2Fgames%2FSample&library_uuid=lib-1&name=Sample',
      ]}
    >
      <ManualIdentifyPage />
    </MemoryRouter>,
  )

  expect(await screen.findByLabelText('Name')).toHaveValue('Sample')
  expect(screen.getByLabelText('Full disk path')).toHaveValue('/games/Sample')
  expect(screen.getByText('Platform: PC Windows')).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Parity Batch Library · PC Windows' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Release' }))
  expect(screen.getByLabelText('Category')).toHaveValue('MAIN_GAME')
  expect(screen.getByLabelText('Status')).toHaveValue('RELEASED')
  expect(screen.getByRole('button', { name: 'Search IGDB by ID' })).toBeEnabled()
  expect(screen.getByText('Enter the IGDB ID of the game.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Search IGDB by ID' }))
  expect(fetchMock).not.toHaveBeenCalledWith(
    expect.stringContaining('/api/search_igdb_by_id'),
    expect.anything(),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Search IGDB' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Use this match' }))
  expect(screen.getByLabelText('Name')).toHaveValue('Sample')
  fireEvent.click(screen.getByRole('tab', { name: 'Taxonomy' }))
  expect(screen.getByLabelText('Adventure')).toBeChecked()
  expect(screen.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }))

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
  await waitFor(() => expect(locationAssign).toHaveBeenCalledWith('/library'))
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
  expect(screen.getByLabelText('IGDB ID')).toHaveValue(123)
})

test('omits read-only game UUID when saving an existing edit form', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
        taxonomies: {
          genres: [],
          game_modes: [],
          themes: [],
          platforms: [],
          player_perspectives: [],
        },
        categories: [{ value: 'MAIN_GAME', label: 'Main Game' }],
        statuses: [{ value: 'RELEASED', label: 'Released' }],
        file_extensions: ['.rom'],
      }) as any
    if (url.endsWith('/api/admin/manual-identify/game-1') && init?.method === 'PUT')
      return response({ redirect_url: '/admin/dashboard' }) as any
    if (url.endsWith('/api/admin/manual-identify/game-1'))
      return response({
        game: {
          uuid: 'game-1',
          igdb_id: 123,
          name: 'Existing game',
          library_uuid: 'lib-1',
          full_disk_path: '/games/existing.rom',
          provider_urls: {},
          genre_ids: [],
          game_mode_ids: [],
          theme_ids: [],
          platform_ids: [],
          player_perspective_ids: [],
        },
        scan_running: false,
      }) as any
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/game_edit/game-1']}>
      <Routes>
        <Route path="/game_edit/:gameUuid" element={<ManualIdentifyPage />} />
        <Route path="/admin/dashboard" element={<div>Saved edit</div>} />
      </Routes>
    </MemoryRouter>,
  )

  expect(await screen.findByLabelText('Name')).toHaveValue('Existing game')
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/admin/manual-identify/game-1',
      expect.objectContaining({ method: 'PUT' }),
    ),
  )
  const updateCall = fetchMock.mock.calls.find(
    ([url, init]) => String(url) === '/api/admin/manual-identify/game-1' && init?.method === 'PUT',
  )
  const updatePayload = JSON.parse((updateCall?.[1] as RequestInit).body as string)
  expect(updatePayload).toMatchObject({
    igdb_id: 123,
    name: 'Existing game',
    library_uuid: 'lib-1',
    full_disk_path: '/games/existing.rom',
  })
  expect(updatePayload).not.toHaveProperty('uuid')
  expect(await screen.findByText('Saved edit')).toBeInTheDocument()
})

test('shows duplicate IGDB ID errors before the long edit form', async () => {
  const conflictMessage = 'The IGDB ID 2000000420 is already used by another game.'
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    if (url.endsWith('/api/admin/manual-identify/game-1') && init?.method === 'PUT')
      return {
        ok: false,
        status: 409,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ error: conflictMessage, message: conflictMessage }),
        text: async () => JSON.stringify({ error: conflictMessage, message: conflictMessage }),
      } as any
    if (url.endsWith('/api/admin/manual-identify/game-1'))
      return response({
        game: {
          uuid: 'game-1',
          igdb_id: 2000777140,
          name: 'Conflict fixture',
          library_uuid: 'lib-1',
          full_disk_path: '/storage/ParityRoot/notes.txt',
          provider_urls: {},
          genre_ids: [],
          game_mode_ids: [],
          theme_ids: [],
          platform_ids: [],
          player_perspective_ids: [],
        },
        scan_running: false,
      }) as any
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/game_edit/game-1']}>
      <Routes>
        <Route path="/game_edit/:gameUuid" element={<ManualIdentifyPage />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(await screen.findByLabelText('Name')).toHaveValue('Conflict fixture')
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(conflictMessage)
  expect(alert.compareDocumentPosition(screen.getByLabelText('Library')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

test('shows an out-of-root path rejection as an accessible save alert', async () => {
  const message = 'The selected game path is outside configured storage roots.'
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    if (url.endsWith('/api/admin/manual-identify'))
      return {
        ok: false,
        status: 403,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ error: message, message }),
        text: async () => JSON.stringify({ error: message, message }),
      } as any
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/add_game_manual?igdb_id=2000777751&library_uuid=lib-1&name=Path+probe&full_disk_path=%2Foutside%2FOneirodexParity%2Fnot-a-real-file.rom']}>
      <Routes>
        <Route path="/add_game_manual" element={<ManualIdentifyPage />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(await screen.findByLabelText('Name')).toHaveValue('Path probe')
  const saveButton = screen.getByRole('button', { name: 'Save' })
  await waitFor(() => expect(saveButton).toBeEnabled())
  fireEvent.click(saveButton)

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(message)
  expect(alert.compareDocumentPosition(screen.getByLabelText('Library')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

test('keeps missing provider-key guidance inline as a polite status', async () => {
  const note = 'MOBYGAMES_API_KEY not configured — empty results. Set env or GlobalSettings.mobygames_api_key.'
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    if (url.startsWith('/api/search_metadata?'))
      return response({
        source: 'mobygames',
        results: [],
        needs_key: true,
        key_configured: false,
        note,
      }) as any
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/add_game_manual?name=Provider+probe']}>
      <Routes>
        <Route path="/add_game_manual" element={<ManualIdentifyPage />} />
      </Routes>
    </MemoryRouter>,
  )

  fireEvent.click(await screen.findByRole('button', { name: 'Search MobyGames' }))

  const status = await screen.findByRole('status')
  expect(status).toHaveTextContent(note)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(status.compareDocumentPosition(screen.getByLabelText('Full disk path')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

test('explains that a game name is required before searching other providers', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/add_game_manual']}>
      <Routes>
        <Route path="/add_game_manual" element={<ManualIdentifyPage />} />
      </Routes>
    </MemoryRouter>,
  )

  const searchButton = await screen.findByRole('button', { name: 'Search MobyGames' })
  expect(searchButton).toBeEnabled()
  fireEvent.click(searchButton)

  expect(await screen.findByRole('status')).toHaveTextContent('Enter a game name first')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/search_metadata?'))).toBe(false)
})

test('explains that a game name is required before searching IGDB', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/add_game_manual']}>
      <Routes>
        <Route path="/add_game_manual" element={<ManualIdentifyPage />} />
      </Routes>
    </MemoryRouter>,
  )

  const searchButton = await screen.findByRole('button', { name: 'Search IGDB', exact: true })
  expect(searchButton).toBeEnabled()
  fireEvent.click(searchButton)

  expect(await screen.findByRole('status')).toHaveTextContent('Enter a game name first')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/search_igdb_by_name?'))).toBe(false)
})

test('keeps an empty IGDB result as inline guidance instead of an error alert', async () => {
  const note = 'No IGDB matches found. You can still enter the metadata manually.'
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    if (url.startsWith('/api/search_igdb_by_name?'))
      return response({ results: [] }) as any
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/add_game_manual?name=No+Match+Probe']}>
      <Routes>
        <Route path="/add_game_manual" element={<ManualIdentifyPage />} />
      </Routes>
    </MemoryRouter>,
  )

  fireEvent.click(await screen.findByRole('button', { name: 'Search IGDB', exact: true }))

  expect(await screen.findByRole('status')).toHaveTextContent(note)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/search_igdb_by_name?'))).toBe(true)
})

test('keeps provider failures beside the provider search controls', async () => {
  const note = 'MobyGames provider temporarily unavailable'
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    if (url.startsWith('/api/search_metadata?'))
      return {
        ...response({ error: note }),
        ok: false,
        status: 503,
      } as any
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/add_game_manual?name=Provider+failure+probe']}>
      <Routes>
        <Route path="/add_game_manual" element={<ManualIdentifyPage />} />
      </Routes>
    </MemoryRouter>,
  )

  fireEvent.click(await screen.findByRole('button', { name: 'Search MobyGames' }))

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(note)
  expect(alert.compareDocumentPosition(screen.getByLabelText('Full disk path')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/search_metadata?'))).toBe(true)
})

test('announces IGDB transport failures beside the search controls', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    if (url.startsWith('/api/search_igdb_by_name?')) throw new TypeError('Failed to fetch')
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/add_game_manual?name=IGDB+transport+probe']}>
      <Routes>
        <Route path="/add_game_manual" element={<ManualIdentifyPage />} />
      </Routes>
    </MemoryRouter>,
  )

  fireEvent.click(await screen.findByRole('button', { name: 'Search IGDB', exact: true }))

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Failed to fetch')
  expect(alert.compareDocumentPosition(screen.getByLabelText('Full disk path')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/search_igdb_by_name?'))).toBe(true)
})

test.each([
  ['/storage/ParityRoot/Alpha.rom', 'Alpha'],
  ['C:\\Games\\Beta.nes', 'Beta'],
  ['/games/Final.Fantasy.IX', 'Final.Fantasy.IX'],
])('derives a title from a path when no explicit name is supplied: %s', async (path, title) => {
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
      file_extensions: ['.rom', '.nes'],
    }),
  ) as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={[`/add_game_manual?full_disk_path=${encodeURIComponent(path)}`]}>
      <ManualIdentifyPage />
    </MemoryRouter>,
  )

  expect(await screen.findByLabelText('Name')).toHaveValue(title)
  expect(screen.getByLabelText('Full disk path')).toHaveValue(path)
})

test('switches non-catalog entry to a generated, locked ID and focuses the empty name', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
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
        categories: [{ value: 'MAIN_GAME', label: 'Main Game' }],
        statuses: [{ value: 'RELEASED', label: 'Released' }],
      }) as any
    if (url === '/api/get_next_custom_igdb_id') return response({ next_id: 2000000420 }) as any
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter
      initialEntries={[
        '/add_game_manual?name=Old+catalog+title&full_disk_path=%2Fgames%2Fcustom&library_uuid=lib-1',
      ]}
    >
      <ManualIdentifyPage />
    </MemoryRouter>,
  )

  const name = await screen.findByLabelText('Name')
  const id = screen.getByLabelText('IGDB ID')
  expect(name).toHaveValue('Old catalog title')
  fireEvent.click(screen.getByRole('button', { name: 'Add non-catalog game' }))

  await waitFor(() => {
    expect(id).toHaveValue(2000000420)
    expect(id).toHaveAttribute('readonly')
    expect(name).toHaveValue('')
    expect(name).toHaveFocus()
  })
  expect(screen.getByRole('button', { name: 'Search IGDB by ID' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Search IGDB', exact: true })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  fireEvent.change(name, { target: { value: 'Custom game' } })
  expect(screen.getByRole('button', { name: 'Search IGDB', exact: true })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  expect(fetchMock).not.toHaveBeenCalledWith(
    expect.stringContaining('/api/search_igdb_by_id'),
    expect.anything(),
  )
})

test('reports custom ID allocation failure without using the legacy fallback ID', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/options'))
      return response({
        libraries: [{ uuid: 'lib-1', name: 'Parity Batch Library', platform_name: 'PC Windows' }],
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
    if (url.endsWith('/api/get_next_custom_igdb_id'))
      return {
        ok: false,
        status: 500,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({
          ok: false,
          error: 'Could not work out the next custom IGDB id',
          error_code: 'internal',
          message: 'Could not work out the next custom IGDB id',
          success: false,
        }),
        text: async () =>
          JSON.stringify({
            ok: false,
            error: 'Could not work out the next custom IGDB id',
            error_code: 'internal',
            message: 'Could not work out the next custom IGDB id',
            success: false,
          }),
      } as any
    return response({}) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter
      initialEntries={[
        '/add_game_manual?name=Keep+this+title&full_disk_path=%2Fgames%2Fcustom&library_uuid=lib-1',
      ]}
    >
      <ManualIdentifyPage />
    </MemoryRouter>,
  )

  const name = await screen.findByLabelText('Name')
  const id = screen.getByLabelText('IGDB ID')
  fireEvent.click(screen.getByRole('button', { name: 'Add non-catalog game' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not allocate a custom catalog ID. Try again.',
  )
  expect(name).toHaveValue('Keep this title')
  expect(id).toHaveValue(null)
  expect(id).not.toHaveAttribute('readonly')
  expect(screen.getByRole('button', { name: 'Search IGDB by ID' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Search IGDB', exact: true })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  expect(
    fetchMock.mock.calls.some(([input]) => String(input) === '/api/admin/manual-identify'),
  ).toBe(false)
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
        initialEntries={[`/game_edit/game-1${fromUnmatched ? '?from_unmatched=true' : ''}`]}
      >
        <Routes>
          <Route path="/game_edit/:gameUuid" element={<ManualIdentifyPage />} />
          <Route path="/library" element={<div>Library page</div>} />
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
