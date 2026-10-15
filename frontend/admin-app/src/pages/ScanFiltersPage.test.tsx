import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ScanFiltersPage } from './ScanFiltersPage'
import { deleteJson, getJson, postJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'

vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn(), deleteJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (original) => ({ ...(await original()), confirmAction: vi.fn() }))
afterEach(() => vi.resetAllMocks())

const filters = [
  { id: 1, filter_pattern: 'GOG', kind: 'name', case_sensitive: 'no' },
  { id: 2, filter_pattern: 'dir:OpenVR*', kind: 'dir', case_sensitive: 'no' },
]

test('lists filters and adds a name tag through the JSON API', async () => {
  vi.mocked(getJson).mockResolvedValueOnce({ filters }).mockResolvedValueOnce({ filters })
  vi.mocked(postJson).mockResolvedValue({ ok: true })
  render(<ScanFiltersPage />)
  expect(await screen.findByText('dir:OpenVR*')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Filter type'), { target: { value: 'name' } })
  fireEvent.change(screen.getByLabelText('Tag to strip'), { target: { value: 'Steam' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save filter' }))
  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/admin/scan-filters', {
      kind: 'name',
      pattern: 'Steam',
      case_sensitive: false,
    }),
  )
  await waitFor(() => expect(getJson).toHaveBeenCalledTimes(2))
})

test('quick add fills the chosen filter type and pattern', async () => {
  vi.mocked(getJson).mockResolvedValue({ filters: [] })
  render(<ScanFiltersPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Skip · OpenVR*' }))
  expect(screen.getByLabelText('Filter type')).toHaveValue('dir')
  expect(screen.getByLabelText('Folder glob')).toHaveValue('OpenVR*')
})

test('removal requires confirmation and calls the resource API', async () => {
  vi.mocked(getJson).mockResolvedValue({ filters })
  vi.mocked(confirmAction).mockResolvedValue(true)
  vi.mocked(deleteJson).mockResolvedValue({ ok: true })
  render(<ScanFiltersPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Remove dir:OpenVR*' }))
  await waitFor(() => expect(deleteJson).toHaveBeenCalledWith('/api/admin/scan-filters/2'))
  expect(confirmAction).toHaveBeenCalled()
})
