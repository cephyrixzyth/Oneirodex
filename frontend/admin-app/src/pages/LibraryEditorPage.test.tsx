import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { LibraryEditorPage } from './LibraryEditorPage'

vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))
import { showToast } from '../utils/toast'

const originalFetch = globalThis.fetch
const originalCreateObjectUrl = URL.createObjectURL
const originalRevokeObjectUrl = URL.revokeObjectURL
const originalCropper = window.Cropper
const originalImageComplete = Object.getOwnPropertyDescriptor(
  HTMLImageElement.prototype,
  'complete',
)
const originalNaturalWidth = Object.getOwnPropertyDescriptor(
  HTMLImageElement.prototype,
  'naturalWidth',
)
afterEach(() => {
  globalThis.fetch = originalFetch
  URL.createObjectURL = originalCreateObjectUrl
  URL.revokeObjectURL = originalRevokeObjectUrl
  if (originalCropper) window.Cropper = originalCropper
  else delete window.Cropper
  if (originalImageComplete)
    Object.defineProperty(HTMLImageElement.prototype, 'complete', originalImageComplete)
  if (originalNaturalWidth)
    Object.defineProperty(HTMLImageElement.prototype, 'naturalWidth', originalNaturalWidth)
  vi.restoreAllMocks()
  vi.clearAllMocks()
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
  expect(showToast).toHaveBeenCalledWith('Library saved.', 'success')
  const update = calls.find(
    ([url, init]) => url.endsWith('/api/admin/libraries/lib-1') && init?.method === 'PUT',
  )
  expect(update?.[1]?.body).toBeInstanceOf(FormData)
  expect((update?.[1]?.body as FormData).get('name')).toBe('NES Collection')
})

test('crops replacement artwork before submitting the library update', async () => {
  const library = {
    uuid: 'lib-1',
    name: 'NES',
    platform: 'NES',
    scan_depth: 1,
    watch_enabled: null,
    image_url: '/static/cover.png',
  }
  const calls: Array<[string, RequestInit | undefined]> = []
  class FakeCropper {
    constructor(_image: HTMLImageElement, _options: unknown) {}
    destroy() {}
    getCroppedCanvas() {
      return {
        toBlob(callback: BlobCallback) {
          callback(new Blob(['cropped-image'], { type: 'image/png' }))
        },
      } as HTMLCanvasElement
    }
    move() {}
    reset() {}
    zoom() {}
  }
  window.Cropper = FakeCropper
  URL.createObjectURL = vi.fn(() => 'blob:cropped-library-image')
  URL.revokeObjectURL = vi.fn()
  Object.defineProperty(HTMLImageElement.prototype, 'complete', { configurable: true, value: true })
  Object.defineProperty(HTMLImageElement.prototype, 'naturalWidth', {
    configurable: true,
    value: 640,
  })
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
  await screen.findByText('Replace library image')
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  expect(input).not.toBeNull()
  const source = new File(['original-image'], 'cover.jpg', { type: 'image/jpeg' })
  fireEvent.change(input, { target: { files: [source] } })
  await screen.findByRole('img', { name: 'Crop library image' })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save Image' })).toBeEnabled())
  fireEvent.click(await screen.findByRole('button', { name: 'Save Image' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save library' }))

  await waitFor(() =>
    expect(
      calls.some(
        ([url, init]) => url.endsWith('/api/admin/libraries/lib-1') && init?.method === 'PUT',
      ),
    ).toBe(true),
  )
  const update = calls.find(
    ([url, init]) => url.endsWith('/api/admin/libraries/lib-1') && init?.method === 'PUT',
  )
  const submittedImage = (update?.[1]?.body as FormData).get('image') as File
  expect(submittedImage).toBeInstanceOf(File)
  expect(submittedImage.name).toBe('cover.jpg')
  expect(submittedImage.type).toBe('image/png')
  expect(showToast).toHaveBeenCalledWith('Library saved.', 'success')
})
