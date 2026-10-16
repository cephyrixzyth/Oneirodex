import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ServerSettingsPage, SERVER_SETTING_GROUPS } from './ServerSettingsPage'
import { getJson, putJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const fields = SERVER_SETTING_GROUPS.flatMap((group) => group.fields)
const settings = Object.fromEntries(
  fields.map((field) => [
    field.key,
    field.type === 'number'
      ? field.key === 'turboDownloadBatchSize'
        ? 100
        : 2
      : field.type === 'url'
        ? 'http://127.0.0.1'
        : field.type
          ? field.key === 'localMetadataFilename'
            ? 'oneirodex.json'
            : 'extras'
          : false,
  ]),
)
const state = {
  settings,
  bounds: {
    scanThreadCount: { min: 1, max: 4, step: 1 },
    turboDownloadThreads: { min: 1, max: 20, step: 1 },
    turboDownloadBatchSize: { min: 10, max: 1000, step: 1 },
    hltbRateLimitDelay: { min: 0.5, max: 10, step: 'any' },
  },
  text_limits: {
    siteUrl: 255,
    updateFolderName: 100,
    extrasFolderName: 100,
    localMetadataFilename: 50,
  },
}

test('all 28 legacy controls retained with named labels and backend bounds', async () => {
  expect(fields).toHaveLength(28)
  vi.mocked(getJson).mockResolvedValue(state)
  render(<ServerSettingsPage />)
  await screen.findByLabelText('Updates folder name')
  for (const field of fields) expect(screen.getByLabelText(field.label)).toBeInTheDocument()
  expect(screen.getAllByRole('checkbox')).toHaveLength(20)
  expect(screen.getByLabelText('Image download threads')).toHaveAttribute('max', '20')
  expect(screen.getByLabelText('Image download batch size')).toHaveAttribute('max', '1000')
  expect(screen.getByRole('link', { name: 'Scan / match policy' })).toHaveAttribute(
    'href',
    '/admin/scan_match',
  )
  expect(putJson).not.toHaveBeenCalled()
  expect(screen.getAllByRole('button', { name: 'Save settings' })[0]).toBeDisabled()
})

test('save sends only changed fields and accepts new public state', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.mocked(putJson).mockResolvedValue({
    ...state,
    settings: { ...settings, updateFolderName: 'patches' },
  })
  render(<ServerSettingsPage />)
  const input = await screen.findByLabelText('Updates folder name')
  fireEvent.change(input, { target: { value: 'patches' } })
  fireEvent.click(screen.getAllByRole('button', { name: 'Save settings' })[0])
  expect(await screen.findByText('Server settings saved.')).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith('/api/admin/server-settings', {
    updateFolderName: 'patches',
  })
  expect(screen.getByLabelText('Enable delete game on disk')).not.toBeChecked()
  expect(screen.getAllByRole('button', { name: 'Save settings' })[0]).toBeDisabled()
})

test('Retry restores load; failed save retains draft and numeric type', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Settings unavailable'))
    .mockResolvedValueOnce(state)
  vi.mocked(putJson).mockRejectedValue(new Error('Save unavailable'))
  render(<ServerSettingsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Settings unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading server settings' }))
  const threads = await screen.findByLabelText('Game scan threads')
  fireEvent.change(threads, { target: { value: '3' } })
  fireEvent.click(screen.getAllByRole('button', { name: 'Save settings' })[0])
  expect(await screen.findByRole('alert')).toHaveTextContent('Save unavailable')
  expect(threads).toHaveValue(3)
  expect(putJson).toHaveBeenCalledWith('/api/admin/server-settings', { scanThreadCount: 3 })
})

test('pending save guards every field and repeated submit', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  let finish!: (value: any) => void
  vi.mocked(putJson).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    }),
  )
  render(<ServerSettingsPage />)
  const input = await screen.findByLabelText('Updates folder name')
  fireEvent.change(input, { target: { value: 'patches' } })
  fireEvent.submit(input.closest('form')!)
  fireEvent.submit(input.closest('form')!)
  expect(putJson).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText('Write metadata file on manual ID')).toBeDisabled()
  finish({ ...state, settings: { ...settings, updateFolderName: 'patches' } })
  await waitFor(() => expect(input).toBeEnabled())
})
