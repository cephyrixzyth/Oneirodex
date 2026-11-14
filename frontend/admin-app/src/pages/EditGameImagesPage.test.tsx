import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { EditGameImagesPage } from './EditGameImagesPage'

const originalFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

test('loads artwork into the shared admin page and uploads a selected kind through the multipart API', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/game-1'))
      return jsonResponse({ ok: true, game: { name: 'Fixture Game' } }) as any
    if (url.endsWith('/api/game_images/game-1'))
      return jsonResponse({
        game_uuid: 'game-1',
        images: [
          { id: 4, image_type: 'cover', url: '/cover.png' },
          { id: 5, image_type: 'screenshot', url: '/screen.png' },
        ],
      }) as any
    if (url.endsWith('/upload_image/game-1'))
      return jsonResponse({ ok: true, url: '/new.png' }) as any
    return jsonResponse({ ok: true, providers: [], sources: [] }) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/edit_game_images/game-1']}>
      <Routes>
        <Route path="/edit_game_images/:gameUuid" element={<EditGameImagesPage />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(await screen.findByRole('heading', { name: /Edit Images/ })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Cover Image' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Artwork Search' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Screenshots' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Other artwork' })).toBeInTheDocument()
  const sections = screen.getAllByRole('heading', {
    name: /^(Cover Image|Artwork Search|Screenshots|Other artwork)$/,
  })
  expect(sections.map((section) => section.textContent)).toEqual([
    'Cover Image',
    'Artwork Search',
    'Screenshots',
    'Other artwork',
  ])
  const artworkSection = screen.getByRole('region', { name: 'Artwork Search' })
  expect(within(artworkSection).getByRole('button', { name: 'Refresh from IGDB' })).toBeEnabled()
  expect(screen.getAllByText('Fixture Game', { exact: true }).length).toBeGreaterThan(0)
  expect(screen.getByRole('img', { name: 'Fixture Game cover' })).toHaveAttribute(
    'src',
    '/cover.png',
  )
  expect(screen.getByRole('img', { name: 'Fixture Game screenshot' })).toHaveAttribute(
    'src',
    '/screen.png',
  )
  const file = new File(['fixture'], 'fixture.png', { type: 'image/png' })
  fireEvent.change(screen.getByLabelText('Upload cover'), { target: { files: [file] } })

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/upload_image/game-1',
      expect.objectContaining({ method: 'POST' }),
    ),
  )
  const uploadCall = fetchMock.mock.calls.find(([url]) => String(url) === '/upload_image/game-1')
  expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData)
})

test('does not offer provider refresh until the game artwork record loads', async () => {
  globalThis.fetch = vi.fn(
    async () => jsonResponse({ code: 'not_found', message: 'Game not found.' }, 404) as any,
  ) as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/edit_game_images/missing-game']}>
      <Routes>
        <Route path="/edit_game_images/:gameUuid" element={<EditGameImagesPage />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(await screen.findByText('Game not found.')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: /Edit Images/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Refresh from IGDB' })).not.toBeInTheDocument()
})

test('accepts dropped screenshot files through the same sequential upload path', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/game-1'))
      return jsonResponse({ ok: true, game: { name: 'Fixture Game' } }) as any
    if (url.endsWith('/api/game_images/game-1'))
      return jsonResponse({ game_uuid: 'game-1', images: [] }) as any
    if (url.endsWith('/upload_image/game-1')) return jsonResponse({ ok: true }) as any
    return jsonResponse({ ok: true, providers: [], sources: [] }) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/edit_game_images/game-1']}>
      <Routes>
        <Route path="/edit_game_images/:gameUuid" element={<EditGameImagesPage />} />
      </Routes>
    </MemoryRouter>,
  )

  const uploadArea = await screen.findByRole('group', { name: 'Screenshot upload area' })
  const file = new File(['fixture screenshot'], 'fixture.png', { type: 'image/png' })
  fireEvent.dragEnter(uploadArea)
  expect(within(uploadArea).getByText('Drop images to upload.')).toBeInTheDocument()
  fireEvent.drop(uploadArea, { dataTransfer: { files: [file] } })

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/upload_image/game-1',
      expect.objectContaining({ method: 'POST' }),
    ),
  )
  const uploadCall = fetchMock.mock.calls.find(([url]) => String(url) === '/upload_image/game-1')
  expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData)
  expect((uploadCall?.[1]?.body as FormData).get('image_type')).toBe('screenshot')
})

test('deletes screenshots immediately and preserves cover confirmation with cancel support', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/admin/manual-identify/game-1'))
      return jsonResponse({ ok: true, game: { name: 'Fixture Game' } }) as any
    if (url.endsWith('/api/game_images/game-1'))
      return jsonResponse({
        game_uuid: 'game-1',
        images: [
          { id: 4, image_type: 'cover', url: '/cover.png' },
          { id: 5, image_type: 'screenshot', url: '/screen.png' },
        ],
      }) as any
    if (url.endsWith('/delete_image')) return jsonResponse({ ok: true }) as any
    return jsonResponse({ ok: true }) as any
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  render(
    <MemoryRouter initialEntries={['/edit_game_images/game-1']}>
      <Routes>
        <Route path="/edit_game_images/:gameUuid" element={<EditGameImagesPage />} />
      </Routes>
    </MemoryRouter>,
  )

  fireEvent.click(await screen.findByRole('button', { name: 'Delete screenshot' }))
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/delete_image',
      expect.objectContaining({ method: 'POST' }),
    ),
  )
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

  fetchMock.mockClear()
  fireEvent.click(screen.getByRole('button', { name: 'Delete cover image' }))
  const dialog = await screen.findByRole('dialog', { name: 'Delete cover image?' })
  expect(
    within(dialog).getByText('Are you sure you want to delete the cover image?'),
  ).toBeInTheDocument()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(fetchMock).not.toHaveBeenCalledWith('/delete_image', expect.anything())

  fireEvent.click(screen.getByRole('button', { name: 'Delete cover image' }))
  const confirmDialog = await screen.findByRole('dialog', { name: 'Delete cover image?' })
  fireEvent.click(within(confirmDialog).getByRole('button', { name: 'Delete cover image' }))
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/delete_image',
      expect.objectContaining({ method: 'POST' }),
    ),
  )
})
