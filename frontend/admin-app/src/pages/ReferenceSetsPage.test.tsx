import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ReferenceSetsPage } from './ReferenceSetsPage'
import { getJson, postJson, deleteJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'
vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
  deleteJson: vi.fn(),
  csrfHeaders: () => ({ 'X-CSRFToken': 'review-csrf' }),
}))
vi.mock('@oneirodex/ui', async (original) => ({ ...(await original()), confirmAction: vi.fn() }))
afterEach(() => {
  vi.resetAllMocks()
  vi.unstubAllGlobals()
})
const row = {
  id: 1,
  library_platform: 'NES',
  region: 'USA',
  source: 'nointro',
  name: 'Synthetic Review',
  entry_count: 1,
}
const state = {
  sets: [],
  platforms: [{ id: 'NES', label: 'Nintendo' }],
  catalog_platforms: [{ id: 'NES', label: 'Nintendo' }],
  regions: ['USA', 'OTHER'],
  sources: ['nointro', 'other'],
  max_dat_bytes: 32 * 1024 * 1024,
}
async function selectFile() {
  const input = await screen.findByLabelText('DAT file')
  fireEvent.change(input, { target: { files: [new File(['<datafile/>'], 'synthetic.xml')] } })
  return input
}

test('empty upload keeps the action available and relies on the required file control', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  render(<ReferenceSetsPage />)
  const input = await screen.findByLabelText('DAT file')
  expect(input).toBeRequired()
  expect(screen.getByRole('button', { name: 'Upload / replace' })).toBeEnabled()
})

test('upload sends multipart with shared CSRF and installs row', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, status: 201, json: async () => ({ reference_set: row }) })
  vi.stubGlobal('fetch', fetcher)
  render(<ReferenceSetsPage />)
  const input = await selectFile()
  fireEvent.submit(input.closest('form')!)
  expect(
    await screen.findByText('Uploaded Synthetic Review: 1 entries for NES/USA'),
  ).toBeInTheDocument()
  const init = fetcher.mock.calls[0][1]
  expect(init.headers).toEqual({ 'X-CSRFToken': 'review-csrf' })
  expect(init.body.get('library_platform')).toBe('NES')
  expect(init.body.get('replace')).toBeNull()
  expect(screen.getByRole('region', { name: 'Installed reference sets table' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Upload / replace' })).toBeEnabled()
})

test('over-limit DAT uses the legacy message and is rejected before upload', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  render(<ReferenceSetsPage />)
  const input = await screen.findByLabelText('DAT file')
  const oversized = new File(['x'], 'too-large.dat', { type: 'application/xml' })
  Object.defineProperty(oversized, 'size', { value: state.max_dat_bytes + 1 })
  fireEvent.change(input, { target: { files: [oversized] } })
  fireEvent.submit(input.closest('form')!)
  expect(await screen.findByRole('alert')).toHaveTextContent('DAT too large (max 32 MiB)')
  expect(fetcher).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Upload / replace' })).toBeEnabled()
})

test('replacement and deletion require separate confirmations, cancellation preserves drafts', async () => {
  vi.mocked(getJson).mockResolvedValue({ ...state, sets: [row] })
  vi.mocked(confirmAction)
    .mockResolvedValueOnce(false)
    .mockResolvedValueOnce(true)
    .mockResolvedValueOnce(false)
    .mockResolvedValueOnce(true)
  vi.mocked(deleteJson).mockResolvedValue({ id: 1 })
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, status: 201, json: async () => ({ reference_set: row }) })
  vi.stubGlobal('fetch', fetcher)
  render(<ReferenceSetsPage />)
  const input = await selectFile()
  fireEvent.submit(input.closest('form')!)
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Upload / replace' })).toBeEnabled(),
  )
  expect(fetcher).not.toHaveBeenCalled()
  fireEvent.submit(input.closest('form')!)
  expect(
    await screen.findByText('Uploaded Synthetic Review: 1 entries for NES/USA'),
  ).toBeInTheDocument()
  expect(fetcher.mock.calls[0][1].body.get('replace')).toBe('true')
  const remove = screen.getByRole('button', { name: 'Delete Synthetic Review (NES/USA)' })
  fireEvent.click(remove)
  await waitFor(() => expect(remove).toBeEnabled())
  expect(deleteJson).not.toHaveBeenCalled()
  fireEvent.click(remove)
  expect(await screen.findByText('Reference set deleted.')).toBeInTheDocument()
  expect(deleteJson).toHaveBeenCalledWith('/api/admin/reference-sets/1')
})

test('load Retry and failed upload retain file/region/source drafts', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('State unavailable'))
    .mockResolvedValueOnce(state)
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue({ ok: false, status: 400, json: async () => ({ error: 'Invalid DAT' }) }),
  )
  render(<ReferenceSetsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('State unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading reference sets' }))
  const input = await selectFile()
  fireEvent.change(screen.getByRole('combobox', { name: 'Upload region' }), {
    target: { value: 'OTHER' },
  })
  fireEvent.submit(input.closest('form')!)
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid DAT')
  expect(screen.getByRole('combobox', { name: 'Upload region' })).toHaveValue('OTHER')
  expect(screen.getByRole('button', { name: 'Upload / replace' })).toBeEnabled()
})

test('rehash/catalog actions retain platform payloads and count feedback without automatic calls', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.mocked(postJson)
    .mockResolvedValueOnce({ hashed: 2, considered: 3, skipped: 1 })
    .mockResolvedValueOnce({ unique_titles: 4, cached_rows: 6, pages: 1 })
  render(<ReferenceSetsPage />)
  await screen.findByLabelText('DAT file')
  expect(postJson).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Rehash platform' }))
  expect(await screen.findByText('Hashed 2 / 3 (skipped 1)')).toBeInTheDocument()
  expect(postJson).toHaveBeenNthCalledWith(1, '/api/reference-sets/rehash', {
    library_platform: 'NES',
  })
  fireEvent.click(screen.getByRole('button', { name: 'Refresh catalog' }))
  expect(await screen.findByText('Cached 4 titles (6 region rows, 1 pages).')).toBeInTheDocument()
  expect(postJson).toHaveBeenNthCalledWith(2, '/api/licensed-catalog/refresh', {
    library_platform: 'NES',
  })
})

test('rehash keeps progress and errors beside its action', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  let finish!: (value: any) => void
  vi.mocked(postJson).mockReturnValue(new Promise((resolve) => { finish = resolve }))
  render(<ReferenceSetsPage />)
  await screen.findByLabelText('DAT file')

  const rehash = screen.getByRole('button', { name: 'Rehash platform' })
  fireEvent.click(rehash)
  expect(screen.getByRole('status')).toHaveTextContent('Hashing…')
  expect(rehash).toBeDisabled()
  finish({ hashed: 2, considered: 3, skipped: 1 })
  expect(await screen.findByRole('status')).toHaveTextContent('Hashed 2 / 3 (skipped 1)')

  vi.mocked(postJson).mockRejectedValueOnce(new Error('Disk read denied'))
  fireEvent.click(rehash)
  expect(await screen.findByRole('status')).toHaveTextContent('Disk read denied')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()

  vi.mocked(postJson).mockRejectedValueOnce(new TypeError('Failed to fetch'))
  fireEvent.click(rehash)
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Failed to fetch'))
})

test('repair dry run renders all four buckets and totals/truncation; pending work locks controls', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  let finish!: (value: any) => void
  vi.mocked(postJson).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    }),
  )
  render(<ReferenceSetsPage />)
  await screen.findByLabelText('DAT file')
  fireEvent.change(screen.getByRole('combobox', { name: 'Repair region' }), {
    target: { value: 'USA' },
  })
  const preview = screen.getByRole('button', { name: 'Preview repairs' })
  fireEvent.click(preview)
  fireEvent.click(preview)
  expect(postJson).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Rehash platform' })).toBeDisabled()
  finish({
    dry_run: true,
    owned_total: 6,
    verified: 1,
    unhashed_name_matches: 1,
    counts: { rename_candidates: 2, hash_mismatches: 1, clone_named: 0, unknown: 1 },
    rename_candidates: [
      { game_uuid: 'r', file_name: 'Different', suggested_name: 'Set name', matched_by: 'crc' },
    ],
    hash_mismatches: [
      { game_uuid: 'm', file_name: 'Mismatch', entry_name: 'Entry', file_crc: 'a', entry_crc: 'b' },
    ],
    clone_named: [],
    unknown: [{ game_uuid: 'u', file_name: 'Unknown', name: 'Unknown', hashed: false }],
  })
  expect(await screen.findByText(/6 owned · 1 verified/)).toBeInTheDocument()
  expect(screen.getByText('Showing the first 1 of 2.')).toBeInTheDocument()
  expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(4)
  expect(postJson).toHaveBeenCalledWith('/api/reference-sets/repair-preview', {
    library_platform: 'NES',
    region: 'USA',
  })
})
