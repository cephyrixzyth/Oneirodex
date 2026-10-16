import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { ManualIdentifyPage } from './ManualIdentifyPage'

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
