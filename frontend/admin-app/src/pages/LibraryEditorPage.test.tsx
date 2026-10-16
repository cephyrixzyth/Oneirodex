import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { LibraryEditorPage } from './LibraryEditorPage'

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

test('loads and saves the full library fields through the native API', async () => {
  const library = {
    uuid: 'lib-1',
    name: 'NES',
    platform: 'NES',
    scan_depth: 2,
    watch_enabled: false,
    image_url: '/static/cover.png',
  }
  const calls: Array<[string, RequestInit | undefined]> = []
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push([url, init])
    if (url.endsWith('/api/admin/library_platforms'))
      return response({
        ok: true,
        platforms: [{ key: 'NES', label: 'Nintendo Entertainment System' }],
      }) as any
    return response({ ok: true, ...library }) as any
  }) as unknown as typeof fetch

  render(
    <MemoryRouter initialEntries={['/admin/library/edit/lib-1']}>
      <Routes>
        <Route path="/admin/library/edit/:libraryUuid" element={<LibraryEditorPage />} />
      </Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByLabelText('Library name')).toHaveValue('NES')
  expect(screen.getByRole('img', { name: 'Current library image' })).toHaveAttribute(
    'src',
    '/static/cover.png',
  )
  fireEvent.change(screen.getByLabelText('Library name'), { target: { value: 'NES Collection' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save library' }))
  await waitFor(() =>
    expect(
      calls.some(
        ([url, init]) => url.endsWith('/api/admin/libraries/lib-1') && init?.method === 'PUT',
      ),
    ).toBe(true),
  )
  expect(await screen.findByRole('status')).toHaveTextContent('Library saved.')
  const update = calls.find(
    ([url, init]) => url.endsWith('/api/admin/libraries/lib-1') && init?.method === 'PUT',
  )
  expect(update?.[1]?.body).toBeInstanceOf(FormData)
  expect((update?.[1]?.body as FormData).get('name')).toBe('NES Collection')
})
