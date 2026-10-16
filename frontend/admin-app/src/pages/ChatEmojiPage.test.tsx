import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ChatEmojiPage } from './ChatEmojiPage'
import { getJson, deleteJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'
vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  deleteJson: vi.fn(),
  csrfHeaders: () => ({ 'X-CSRFToken': 'review-csrf' }),
}))
vi.mock('@oneirodex/ui', async (original) => ({ ...(await original()), confirmAction: vi.fn() }))
afterEach(() => {
  vi.resetAllMocks()
  vi.unstubAllGlobals()
})
const emoji = {
  id: 1,
  slug: 'review',
  label: 'Review',
  emoji: ':review:',
  url: '/static/library/chat-emoji/review.webp',
}
const state = {
  emojis: [],
  max_custom: 20,
  limits: { max_upload_bytes: 256 * 1024, max_edge_px: 128 },
}

test('multipart upload uses shared csrf and shows the installed preview', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, status: 201, json: async () => ({ ok: true, emoji }) })
  vi.stubGlobal('fetch', fetcher)
  render(<ChatEmojiPage />)
  const slug = await screen.findByLabelText('Slug')
  fireEvent.change(slug, { target: { value: 'review' } })
  fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'Review' } })
  fireEvent.change(screen.getByLabelText('Image'), {
    target: { files: [new File(['test'], 'review.png', { type: 'image/png' })] },
  })
  fireEvent.submit(slug.closest('form')!)
  expect(await screen.findByText('Custom emoji uploaded.')).toBeInTheDocument()
  const init = fetcher.mock.calls[0][1]
  expect(init.headers).toEqual({ 'X-CSRFToken': 'review-csrf' })
  expect(init.body).toBeInstanceOf(FormData)
  expect(init.body.get('slug')).toBe('review')
  expect(screen.getByRole('img', { name: 'Review' })).toHaveAttribute('src', emoji.url)
  expect(screen.getByRole('region', { name: 'Custom emoji table' })).toHaveAttribute(
    'tabindex',
    '0',
  )
  expect(slug).toHaveValue('')
})

test('failed upload retains entered draft', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ ok: false, error: 'Slug already exists' }),
    }),
  )
  render(<ChatEmojiPage />)
  const slug = await screen.findByLabelText('Slug')
  fireEvent.change(slug, { target: { value: 'review' } })
  fireEvent.change(screen.getByLabelText('Image'), {
    target: { files: [new File(['test'], 'review.png')] },
  })
  fireEvent.submit(slug.closest('form')!)
  expect(await screen.findByRole('alert')).toHaveTextContent('Slug already exists')
  expect(slug).toHaveValue('review')
})

test('deletion requires confirmation; cap blocks uploads and removal restores capacity', async () => {
  vi.mocked(getJson).mockResolvedValue({ ...state, max_custom: 1, emojis: [emoji] })
  vi.mocked(confirmAction).mockResolvedValueOnce(false).mockResolvedValueOnce(true)
  vi.mocked(deleteJson).mockResolvedValue({ ok: true })
  render(<ChatEmojiPage />)
  const button = await screen.findByRole('button', { name: 'Delete :review:' })
  expect(screen.getByRole('button', { name: 'Upload emoji' })).toBeDisabled()
  fireEvent.click(button)
  await waitFor(() => expect(confirmAction).toHaveBeenCalledTimes(1))
  expect(deleteJson).not.toHaveBeenCalled()
  fireEvent.click(button)
  expect(await screen.findByText('Custom emoji deleted.')).toBeInTheDocument()
  expect(deleteJson).toHaveBeenCalledWith('/api/admin/chat-emoji/review')
  expect(screen.getByRole('button', { name: 'Upload emoji' })).toBeEnabled()
})

test('load failure guards uploads and Retry recovers', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Emoji unavailable'))
    .mockResolvedValueOnce(state)
  render(<ChatEmojiPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Emoji unavailable')
  expect(screen.getByRole('button', { name: 'Upload emoji' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading emoji' }))
  expect(await screen.findByText('No custom emoji yet.')).toBeInTheDocument()
})
