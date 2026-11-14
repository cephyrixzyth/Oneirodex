import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { LibraryImageCropper } from './LibraryImageCropper'

const originalCreateObjectUrl = URL.createObjectURL
const originalRevokeObjectUrl = URL.revokeObjectURL
const originalCropper = window.Cropper

afterEach(() => {
  URL.createObjectURL = originalCreateObjectUrl
  URL.revokeObjectURL = originalRevokeObjectUrl
  if (originalCropper) window.Cropper = originalCropper
  else delete window.Cropper
  vi.restoreAllMocks()
})

test('crops a selected file to a 512px square PNG with zoom, reset, and keyboard panning', async () => {
  const calls: Array<{ method: string; args?: unknown[] }> = []
  class FakeCropper {
    constructor(_image: HTMLImageElement, options: unknown) {
      calls.push({ method: 'construct', args: [options] })
    }
    destroy() {
      calls.push({ method: 'destroy' })
    }
    getCroppedCanvas(options: unknown) {
      calls.push({ method: 'crop', args: [options] })
      return {
        toBlob(callback: BlobCallback) {
          callback(new Blob(['cropped'], { type: 'image/png' }))
        },
      } as HTMLCanvasElement
    }
    move(...args: number[]) {
      calls.push({ method: 'move', args })
    }
    reset() {
      calls.push({ method: 'reset' })
    }
    zoom(...args: number[]) {
      calls.push({ method: 'zoom', args })
    }
  }
  window.Cropper = FakeCropper
  URL.createObjectURL = vi.fn(() => 'blob:library-image')
  URL.revokeObjectURL = vi.fn()
  const onSave = vi.fn()
  const onCancel = vi.fn()
  const source = new File(['source'], 'cover.jpg', { type: 'image/jpeg' })

  render(<LibraryImageCropper file={source} onSave={onSave} onCancel={onCancel} />)
  const image = screen.getByRole('img', { name: 'Crop library image' })
  const imageLoadListener = vi.spyOn(image, 'addEventListener')
  Object.defineProperty(image, 'complete', { configurable: true, value: false })
  Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 640 })
  await waitFor(() =>
    expect(imageLoadListener).toHaveBeenCalledWith('load', expect.any(Function), { once: true }),
  )
  fireEvent.load(image)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save Image' })).toBeEnabled())

  fireEvent.click(screen.getByRole('button', { name: 'Zoom In' }))
  fireEvent.click(screen.getByRole('button', { name: 'Zoom Out' }))
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
  fireEvent.keyDown(document, { key: 'ArrowLeft' })
  fireEvent.keyDown(document, { key: '=' })
  fireEvent.click(screen.getByRole('button', { name: 'Save Image' }))

  await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
  const cropped = onSave.mock.calls[0][0] as File
  expect(cropped.name).toBe('cover.jpg')
  expect(cropped.type).toBe('image/png')
  expect(calls).toContainEqual({ method: 'zoom', args: [0.1] })
  expect(calls).toContainEqual({ method: 'zoom', args: [-0.1] })
  expect(calls).toContainEqual({ method: 'reset' })
  expect(calls).toContainEqual({ method: 'move', args: [-10, 0] })
  expect(calls).toContainEqual({
    method: 'crop',
    args: [{ width: 512, height: 512, imageSmoothingEnabled: true, imageSmoothingQuality: 'high' }],
  })
})
