import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  const allRows = Array.from({ length: 51 }, (_, index) => ({
    id: `folder-${index}`,
    folder_path: `/storage/review/page-${index}`,
    status: 'Unmatched',
    library_uuid: 'library-1',
    library_name: 'Review Library',
    platform_name: 'PCWIN',
    rom_region: 'USA',
  }))
  vi.mocked(getJson).mockImplementation(async (url) => {
    const value = String(url)
    if (value === '/api/get_libraries') {
      return [{ uuid: 'library-1', name: 'Review Library', platform_name: 'PCWIN' }]
    }
    const params = new URL(value, 'http://oneirodex.test').searchParams
    const offset = Number(params.get('offset') || 0)
    if (params.get('paginate') === '0') return allRows
    return {
      items: [allRows[offset]],
      total: allRows.length,
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
    expect.stringContaining('paginate=1&limit=150&offset=0'),
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  )
  expect(screen.getByRole('group', { name: 'Layout filter' })).toBeInTheDocument()
  expect(screen.getByRole('group', { name: 'Triage filter' })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: /Folder/ })).toHaveAttribute(
    'aria-sort',
    'ascending',
  )

  fireEvent.change(screen.getByLabelText('Rows per page'), { target: { value: '50' } })
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

  fireEvent.click(
    within(screen.getByRole('group', { name: 'Layout filter' })).getByRole('button', {
      name: 'All',
    }),
  )
  await waitFor(() => expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() =>
    expect(getJson).toHaveBeenCalledWith(
      expect.stringContaining('paginate=1&limit=50&offset=50'),
      expect.anything(),
    ),
  )
  expect(await screen.findByText('/storage/review/page-50')).toBeInTheDocument()
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

test('computed filters paginate across every matching row and report the filtered total', async () => {
  const allRows = Array.from({ length: 51 }, (_, index) => ({
    id: `rom-${index}`,
    folder_path: `/storage/review/Game-${index}.nes`,
    status: 'Unmatched',
    library_name: 'Review Library',
    platform_name: 'NES',
  }))
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (String(url) === '/api/get_libraries') return []
    const params = new URL(String(url), 'http://oneirodex.test').searchParams
    if (params.get('paginate') === '0') return allRows
    return { items: [allRows[0]], total: allRows.length, count: 1 }
  })

  render(
    <MemoryRouter initialEntries={['/scan_management?active_tab=unmatched']}>
      <ScanUnmatchedPage />
    </MemoryRouter>,
  )

  expect(await screen.findByText('/storage/review/Game-0.nes')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Rows per page'), { target: { value: '50' } })
  fireEvent.click(screen.getByRole('button', { name: 'ROM files library' }))

  expect(await screen.findByText('Showing 1–50 of 51')).toBeInTheDocument()
  expect(screen.getByText('/storage/review/Game-0.nes')).toBeInTheDocument()
  expect(screen.queryByText('/storage/review/Game-50.nes')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))

  expect(await screen.findByText('Showing 51–51 of 51')).toBeInTheDocument()
  expect(screen.getByText('/storage/review/Game-50.nes')).toBeInTheDocument()
  expect(screen.queryByText('/storage/review/Game-0.nes')).not.toBeInTheDocument()
  expect(getJson).toHaveBeenCalledWith(
    expect.stringContaining('paginate=0'),
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  )
})

test('keeps selected rows across server pages and applies batch actions to every selection', async () => {
  const allRows = Array.from({ length: 51 }, (_, index) => ({
    id: `folder-${index}`,
    folder_path: `/storage/review/page-${String(index).padStart(2, '0')}`,
    status: 'Unmatched',
    library_name: 'Review Library',
    platform_name: 'PCWIN',
  }))
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (String(url) === '/api/get_libraries') return []
    const params = new URL(String(url), 'http://oneirodex.test').searchParams
    const offset = Number(params.get('offset') || 0)
    const limit = Number(params.get('limit') || 150)
    return { items: allRows.slice(offset, offset + limit), total: allRows.length }
  })
  vi.mocked(postJson).mockResolvedValue({ marked: 2 })

  render(
    <MemoryRouter initialEntries={['/scan_management?active_tab=unmatched']}>
      <ScanUnmatchedPage />
    </MemoryRouter>,
  )

  fireEvent.click(
    await screen.findByRole('checkbox', { name: 'Select folder /storage/review/page-00' }),
  )
  fireEvent.change(screen.getByLabelText('Rows per page'), { target: { value: '50' } })
  await screen.findByText('/storage/review/page-00')
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  fireEvent.click(
    await screen.findByRole('checkbox', { name: 'Select folder /storage/review/page-50' }),
  )

  expect(screen.getByRole('group', { name: 'Selected folder actions' })).toHaveTextContent(
    '2 selected',
  )
  fireEvent.click(
    within(screen.getByRole('group', { name: 'Selected folder actions' })).getByRole('button', {
      name: 'Mark Soft',
    }),
  )

  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/unmatched_folders/batch/mark_kind', {
      ids: ['folder-0', 'folder-50'],
      item_kind: 'experience',
    }),
  )
  expect(await screen.findByText('Marked 2 of 2 selected as experience.')).toBeInTheDocument()
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
