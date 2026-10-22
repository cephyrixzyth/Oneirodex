import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { CreateLibraryForm } from './CreateLibraryForm'

const queueLeafScan = vi.fn()
vi.mock('../api/proposeLeafLibrariesApi', () => ({
  queueLeafScan: (...args: unknown[]) => queueLeafScan(...args),
}))

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
  queueLeafScan.mockReset()
})

function response(body: unknown) {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

test('crops library artwork to PNG before creating and queueing the library', async () => {
  const requests: Array<[string, RequestInit | undefined]> = []
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
  queueLeafScan.mockResolvedValue({ ok: true, data: { message: 'First scan queued.' } })
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    requests.push([url, init])
    if (url.endsWith('/api/admin/library_platforms'))
      return response({ platforms: [{ key: 'NES', label: 'Nintendo Entertainment System' }] }) as any
    return response({ ok: true, library_uuid: 'new-library-1' }) as any
  }) as unknown as typeof fetch

  const onCreated = vi.fn()
  const onComplete = vi.fn()
  render(<CreateLibraryForm onCreated={onCreated} onComplete={onComplete} />)
  await screen.findByRole('option', { name: 'Nintendo Entertainment System' })
  fireEvent.change(screen.getByLabelText('Library name'), { target: { value: 'NES Library' } })
  fireEvent.change(screen.getByPlaceholderText('/storage/games/nes'), {
    target: { value: '/storage/games/nes' },
  })
  const source = new File(['original-image'], 'cover.jpg', { type: 'image/jpeg' })
  fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, {
    target: { files: [source] },
  })
  await screen.findByRole('img', { name: 'Crop library image' })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save Image' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Save Image' }))
  fireEvent.click(screen.getByRole('button', { name: 'Create library and start scan' }))

  await waitFor(() =>
    expect(requests.some(([url, init]) => url.endsWith('/api/admin/libraries') && init?.method === 'POST')).toBe(true),
  )
  const createRequest = requests.find(
    ([url, init]) => url.endsWith('/api/admin/libraries') && init?.method === 'POST',
  )
  const form = createRequest?.[1]?.body as FormData
  const submittedImage = form.get('image') as File
  expect(submittedImage).toBeInstanceOf(File)
  expect(submittedImage.name).toBe('cover.jpg')
  expect(submittedImage.type).toBe('image/png')
  expect(form.get('name')).toBe('NES Library')
  expect(queueLeafScan).toHaveBeenCalledWith({
    uuid: 'new-library-1',
    path: '/storage/games/nes',
    scan_mode: 'folders',
  })
  expect(onCreated).toHaveBeenCalledOnce()
  expect(onComplete).toHaveBeenCalledOnce()
})
