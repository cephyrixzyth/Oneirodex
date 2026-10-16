import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

  expect(await screen.findByRole('heading', { name: 'Edit game images' })).toBeInTheDocument()
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
