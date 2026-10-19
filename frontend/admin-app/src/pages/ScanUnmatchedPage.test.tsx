import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { getJson, postJson } from '../api/adminApi'
import { ScanUnmatchedPage } from './ScanUnmatchedPage'

vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
}))

afterEach(() => vi.resetAllMocks())

test('renders a paginated scan table, carries link feedback, and requests the next page', async () => {
  vi.mocked(getJson).mockImplementation(async (url) => {
    const value = String(url)
    if (value === '/api/get_libraries') {
      return [{ uuid: 'library-1', name: 'Review Library', platform_name: 'PCWIN' }]
    }
    const params = new URL(value, 'http://oneirodex.test').searchParams
    const offset = Number(params.get('offset') || 0)
    return {
      items: [
        {
          id: `folder-${offset}`,
          folder_path: `/storage/review/page-${offset}`,
          status: 'Unmatched',
          library_uuid: 'library-1',
          library_name: 'Review Library',
          platform_name: 'PCWIN',
          rom_region: 'USA',
        },
      ],
      total: 151,
      count: 1,
    }
  })

  render(
    <MemoryRouter
      initialEntries={[
        {
          pathname: '/scan_management',
          search: '?active_tab=unmatched',
          state: { linkSuccess: "Linked existing game 'Review Game' to this folder." },
        },
      ]}
    >
      <ScanUnmatchedPage />
    </MemoryRouter>,
  )

  expect(await screen.findByText('/storage/review/page-0')).toBeInTheDocument()
  expect(screen.getByText("Linked existing game 'Review Game' to this folder.")).toBeInTheDocument()
  expect(screen.queryByText('Dupe glance')).not.toBeInTheDocument()
  expect(getJson).toHaveBeenCalledWith(
    expect.stringContaining('limit=150&offset=0&paginate=1'),
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  )
  expect(screen.getByRole('group', { name: 'Layout filter' })).toBeInTheDocument()
  expect(screen.getByRole('group', { name: 'Triage filter' })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: /Folder/ })).toHaveAttribute(
    'aria-sort',
    'ascending',
  )

  fireEvent.click(screen.getByRole('button', { name: 'ROM files library' }))
  expect(await screen.findByText('No folders for this filter.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Folder library' }))
  expect(await screen.findByText('/storage/review/page-0')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('checkbox', { name: 'Select folder /storage/review/page-0' }))
  expect(screen.getByRole('group', { name: 'Selected folder actions' })).toBeInTheDocument()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  fireEvent.click(screen.getByRole('button', { name: 'Clear selected' }))
  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/unmatched_folders/batch/clear', {
      ids: ['folder-0'],
    }),
  )

  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() =>
    expect(getJson).toHaveBeenCalledWith(
      expect.stringContaining('limit=150&offset=150&paginate=1'),
      expect.anything(),
    ),
  )
  expect(await screen.findByText('/storage/review/page-150')).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledTimes(1)
})

test('disk deletion requires confirmation before the destructive request', async () => {
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (String(url) === '/api/get_libraries') return []
    return {
      items: [
        { id: 'folder-delete', folder_path: '/storage/review/delete-me', status: 'Unmatched' },
      ],
      total: 1,
      count: 1,
    }
  })
  vi.mocked(postJson).mockResolvedValue({
    message: 'Item deleted successfully. Database entry removed.',
  })
  vi.spyOn(window, 'confirm').mockReturnValue(false)

  render(
    <MemoryRouter initialEntries={['/scan_management?active_tab=unmatched']}>
      <ScanUnmatchedPage />
    </MemoryRouter>,
  )

  await screen.findByText('/storage/review/delete-me')
  fireEvent.click(screen.getByRole('button', { name: 'Delete from disk' }))
  expect(window.confirm).toHaveBeenCalledWith(
    'Are you sure you want to delete the folder /storage/review/delete-me FROM DISK?',
  )
  expect(postJson).not.toHaveBeenCalled()
})

test('saves the legacy soft search name without renaming the folder path', async () => {
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (String(url) === '/api/get_libraries') return []
    return {
      items: [
        {
          id: 'folder-name',
          folder_path: '/storage/review/Original Name',
          folder_name: 'Original Name',
          search_name: 'Old Search Name',
          status: 'Unmatched',
        },
      ],
      total: 1,
      count: 1,
    }
  })
  vi.mocked(postJson).mockResolvedValue({
    id: 'folder-name',
    folder_path: '/storage/review/Original Name',
    search_name: 'Corrected Search Name',
    disk_rename: false,
  })

  render(
    <MemoryRouter initialEntries={['/scan_management?active_tab=unmatched']}>
      <ScanUnmatchedPage />
    </MemoryRouter>,
  )
  const nameInput = await screen.findByRole('textbox', { name: 'Search name' })
  fireEvent.change(nameInput, { target: { value: 'Corrected Search Name' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save name' }))

  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/unmatched_folders/folder-name/name', {
      search_name: 'Corrected Search Name',
      display_name: 'Corrected Search Name',
    }),
  )
  expect(await screen.findByText(/folder on disk was not renamed/i)).toBeInTheDocument()
  expect(screen.getByText('/storage/review/Original Name')).toBeInTheDocument()
})
