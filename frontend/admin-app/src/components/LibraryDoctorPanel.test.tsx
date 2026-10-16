import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { postJson } from '../api/adminApi'
import { LibraryDoctorPanel } from './LibraryDoctorPanel'
import { confirmAction } from '@oneirodex/ui'

vi.mock('../api/adminApi', () => ({ postJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@oneirodex/ui')>()
  return { ...actual, confirmAction: vi.fn() }
})

beforeEach(() => {
  vi.mocked(postJson).mockReset()
  vi.mocked(confirmAction).mockReset()
})

test('previews folder names and leaves write and rename actions disabled until a preview exists', async () => {
  vi.mocked(postJson).mockResolvedValue({
    rows: [
      {
        path: '/storage/games/example',
        raw_name: 'Example (USA) [!]',
        cleaned_name: 'Example',
        suggested_rename: 'Example',
        rename_plan: [
          {
            kind: 'root_folder',
            from_path: '/storage/games/example',
            to_path: '/storage/games/Example',
          },
        ],
      },
    ],
  })
  render(<LibraryDoctorPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Open folder name tools' }))
  expect(screen.getByRole('button', { name: 'Save as suggestions' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Rename on disk' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText(/Folders to check/i), {
    target: { value: '/storage/games' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Preview folder names' }))
  expect(await screen.findByText('Example (USA) [!]')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save as suggestions' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Rename on disk' })).toBeEnabled()
  expect(postJson).toHaveBeenCalledWith('/api/library_tools/doctor/dry_run', {
    roots: ['/storage/games'],
    template: '{title}',
  })
})

test('requires the shared confirmation before saving proposal sidecars', async () => {
  vi.mocked(postJson)
    .mockResolvedValueOnce({
      rows: [{ path: '/storage/games/example', raw_name: 'Example', cleaned_name: 'Example' }],
    })
    .mockResolvedValueOnce({ results: [{ path: '/storage/games/example', ok: true }] })
  vi.mocked(confirmAction).mockResolvedValue(false)
  render(<LibraryDoctorPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Open folder name tools' }))
  fireEvent.change(screen.getByLabelText(/Folders to check/i), {
    target: { value: '/storage/games' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Preview folder names' }))
  await screen.findByRole('table', { name: 'Folder name preview' })
  fireEvent.click(screen.getByRole('button', { name: 'Save as suggestions' }))
  await waitFor(() => expect(confirmAction).toHaveBeenCalled())
  expect(confirmAction).toHaveBeenCalledWith(
    expect.objectContaining({ confirmLabel: 'Save suggestions' }),
  )
  expect(postJson).toHaveBeenCalledTimes(1)

  vi.mocked(confirmAction).mockResolvedValue(true)
  fireEvent.click(screen.getByRole('button', { name: 'Save as suggestions' }))
  await screen.findByText(/suggestions saved/)
  expect(postJson).toHaveBeenLastCalledWith('/api/library_tools/doctor/write_proposals', {
    rows: [{ path: '/storage/games/example', raw_name: 'Example', cleaned_name: 'Example' }],
  })
})

test('requires the destructive confirmation before applying root folder renames', async () => {
  vi.mocked(postJson)
    .mockResolvedValueOnce({
      rows: [{ path: '/storage/games/example', raw_name: 'Example', cleaned_name: 'Example' }],
    })
    .mockResolvedValueOnce({ results: [{ path: '/storage/games/example', ok: true }] })
  vi.mocked(confirmAction).mockResolvedValue(true)
  render(<LibraryDoctorPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Open folder name tools' }))
  fireEvent.change(screen.getByLabelText(/Folders to check/i), {
    target: { value: '/storage/games' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Preview folder names' }))
  await screen.findByRole('table', { name: 'Folder name preview' })
  fireEvent.click(screen.getByRole('button', { name: 'Rename on disk' }))
  await waitFor(() =>
    expect(confirmAction).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Rename 1 folders on disk?',
        tone: 'danger',
        confirmLabel: 'Rename folders',
      }),
    ),
  )
  await screen.findByText(/rename run finished/)
  expect(postJson).toHaveBeenLastCalledWith('/api/library_tools/doctor/apply_renames', {
    rows: [{ path: '/storage/games/example', raw_name: 'Example', cleaned_name: 'Example' }],
    template: '{title}',
  })
})
