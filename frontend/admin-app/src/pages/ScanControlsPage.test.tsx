import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ScanControlsPage } from './ScanControlsPage'
import { getJson, postJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'
import { MemoryRouter } from 'react-router-dom'

const { scan } = vi.hoisted(() => ({ scan: vi.fn() }))
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@oneirodex/ui')>()
  return { ...actual, confirmAction: vi.fn() }
})
vi.mock('../hooks/useLibraryScan', () => ({
  useLibraryScan: () => ({
    conflictOpen: false,
    scanning: false,
    startScan: scan,
    onConflictChoose: vi.fn(),
    onConflictClose: vi.fn(),
  }),
}))
afterEach(() => {
  vi.resetAllMocks()
})

function renderPage(path = '/admin/scan-controls') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <ScanControlsPage />
    </MemoryRouter>,
  )
}

test('loads library and root choices and submits Auto Scan settings through the shared queue hook', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/get_libraries'
      ? [{ uuid: 'lib-1', name: 'Nintendo', last_scan_folder: '' }]
      : {
          roots: [
            {
              id: 'games',
              label: 'Games',
              path: '/games',
              default: true,
              exists: true,
              read: true,
            },
          ],
        },
  )
  renderPage()
  await screen.findByRole('option', { name: 'Nintendo' })
  fireEvent.change(screen.getByLabelText('Folder inside scan location'), {
    target: { value: 'Nintendo' },
  })
  fireEvent.click(screen.getByLabelText('Download missing images'))
  fireEvent.change(screen.getByLabelText('Repeat schedule'), { target: { value: 'interval' } })
  fireEvent.change(screen.getByLabelText('Interval'), { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Start and schedule scan' }))
  await waitFor(() =>
    expect(scan).toHaveBeenCalledWith({
      libraryUuid: 'lib-1',
      folder: 'Nintendo',
      settings: expect.objectContaining({
        use_library_root: true,
        library_root: 'games',
        scan_mode: 'auto',
        download_missing_images: true,
        schedule: 'interval',
        schedule_interval_value: 2,
        schedule_interval_unit: 'hours',
      }),
    }),
  )
})

test('keeps the legacy 10080 interval maximum for both hour and minute schedules', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/get_libraries'
      ? [{ uuid: 'lib-1', name: 'Nintendo', last_scan_folder: '' }]
      : { roots: [] },
  )
  renderPage()
  await screen.findByRole('option', { name: 'Nintendo' })
  fireEvent.change(screen.getByLabelText('Repeat schedule'), { target: { value: 'interval' } })
  expect(screen.getByLabelText('Interval')).toHaveAttribute('max', '10080')
  fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'minutes' } })
  expect(screen.getByLabelText('Interval')).toHaveAttribute('max', '10080')
})

test('keeps automatic scan and manual identification together on the scan management page', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/get_libraries' ? [] : { roots: [] },
  )
  renderPage()
  expect(await screen.findByRole('heading', { name: 'Scan management' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Automatic scan' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Manual identify' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start scan' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'List games to identify' })).toBeInTheDocument()
})

test('lists manual identify candidates without starting a scan and links to the native identify form', async () => {
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (url === '/api/get_libraries')
      return [{ uuid: 'lib-1', name: 'Nintendo', last_scan_folder: '' }]
    if (url === '/api/library_roots')
      return {
        roots: [
          { id: 'games', label: 'Games', path: '/games', default: true, exists: true, read: true },
        ],
      }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.mocked(postJson).mockResolvedValue({
    action: 'preview',
    read_only: true,
    games: [{ name: 'Metroid', full_path: '/games/Metroid' }],
  })
  renderPage('/scan_management?active_tab=manual')
  await screen.findByRole('option', { name: 'Nintendo' })
  fireEvent.click(screen.getByRole('button', { name: 'List games to identify' }))
  const identify = await screen.findByRole('link', { name: 'Identify' })
  expect(identify).toHaveAttribute(
    'href',
    '/add_game_manual?full_disk_path=%2Fgames%2FMetroid&library_uuid=lib-1',
  )
  expect(postJson).toHaveBeenCalledWith(
    '/api/library_tools/manual_identify/list',
    expect.objectContaining({
      library_uuid: 'lib-1',
      root: 'games',
      queue_policy: 'inspect',
    }),
  )
  expect(scan).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Folder inside scan location'), {
    target: { value: 'Other' },
  })
  expect(screen.queryByRole('link', { name: 'Identify' })).not.toBeInTheDocument()
})

test('shows a rejected manual folder as an accessible error without starting a scan', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/get_libraries'
      ? [{ uuid: 'lib-1', name: 'Nintendo', last_scan_folder: '' }]
      : {
          roots: [
            {
              id: 'games',
              label: 'Games',
              path: '/games',
              default: true,
              exists: true,
              read: true,
            },
          ],
        },
  )
  vi.mocked(postJson).mockRejectedValue(
    new Error('The selected folder does not exist or cannot be read'),
  )
  renderPage('/scan_management?active_tab=manual')
  await screen.findByRole('option', { name: 'Nintendo' })
  fireEvent.click(screen.getByRole('button', { name: 'List games to identify' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'The selected folder does not exist or cannot be read',
  )
  expect(scan).not.toHaveBeenCalled()
})

test('shows the busy-scan queue result from the manual list action', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/get_libraries'
      ? [{ uuid: 'lib-1', name: 'Nintendo' }]
      : {
          roots: [
            {
              id: 'games',
              label: 'Games',
              path: '/games',
              default: true,
              exists: true,
              read: true,
            },
          ],
        },
  )
  vi.mocked(postJson).mockResolvedValue({
    action: 'queued',
    message: 'Queued manual scan.',
    read_only: false,
  })
  renderPage('/scan_management?active_tab=manual')
  await screen.findByRole('option', { name: 'Nintendo' })
  fireEvent.click(screen.getByRole('button', { name: 'List games to identify' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Queued manual scan.')
  expect(screen.queryByRole('link', { name: 'Identify' })).not.toBeInTheDocument()
  expect(scan).not.toHaveBeenCalled()
})

test('asks before queueing or forcing a manual scan when another scan is active', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/get_libraries'
      ? [{ uuid: 'lib-1', name: 'Nintendo' }]
      : {
          roots: [
            {
              id: 'games',
              label: 'Games',
              path: '/games',
              default: true,
              exists: true,
              read: true,
            },
          ],
        },
  )
  vi.mocked(postJson)
    .mockResolvedValueOnce({ action: 'conflict', read_only: true })
    .mockResolvedValueOnce({ action: 'queued', message: 'Queued manual scan.', read_only: false })
  renderPage('/scan_management?active_tab=manual')
  await screen.findByRole('option', { name: 'Nintendo' })
  fireEvent.click(screen.getByRole('button', { name: 'List games to identify' }))
  const queue = await screen.findByRole('button', { name: 'Queue this scan' })
  fireEvent.click(queue)
  await waitFor(() =>
    expect(postJson).toHaveBeenLastCalledWith(
      '/api/library_tools/manual_identify/list',
      expect.objectContaining({ queue_policy: 'queue' }),
    ),
  )
  expect(await screen.findByRole('status')).toHaveTextContent('Queued manual scan.')
  expect(postJson).toHaveBeenCalledTimes(2)
})

test('restores the selected library from scan-management deep links', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/get_libraries'
      ? [
          { uuid: 'lib-1', name: 'Nintendo' },
          { uuid: 'lib-2', name: 'PC' },
        ]
      : {
          roots: [
            {
              id: 'games',
              label: 'Games',
              path: '/games',
              default: true,
              exists: true,
              read: true,
            },
          ],
        },
  )
  renderPage('/scan_management?active_tab=manual&library_uuid=lib-2')
  const library = await screen.findByLabelText('Library')
  await waitFor(() => expect(library).toHaveValue('lib-2'))
})

test('manual deep link focuses identification and hides automatic scan actions', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/get_libraries'
      ? [{ uuid: 'lib-1', name: 'Nintendo', last_scan_folder: '' }]
      : {
          roots: [
            {
              id: 'games',
              label: 'Games',
              path: '/games',
              default: true,
              exists: true,
              read: true,
            },
          ],
        },
  )

  renderPage('/scan_management?active_tab=manual')

  expect(await screen.findByRole('heading', { name: 'Scan management' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Manual identify' })).toBeInTheDocument()
  expect(screen.getByRole('group', { name: 'Scan options' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'List games to identify' })).toBeInTheDocument()
  expect(screen.getByLabelText('Remove games whose files are missing')).toBeInTheDocument()
  expect(screen.getByLabelText('Download missing images')).toBeInTheDocument()
  expect(screen.getByLabelText('Repeat schedule')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start scan' })).toBeInTheDocument()
})

test('confirms linking a listed folder to an existing game before posting', async () => {
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (url === '/api/get_libraries') return [{ uuid: 'lib-1', name: 'Nintendo' }]
    if (url === '/api/library_roots')
      return {
        roots: [
          { id: 'games', label: 'Games', path: '/games', default: true, exists: true, read: true },
        ],
      }
    if (url === '/api/admin/games_search?q=Metroid')
      return [{ uuid: 'game-1', name: 'Metroid Prime', full_disk_path: '/games/Metroid Prime' }]
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.mocked(postJson).mockImplementation(async (url) =>
    url === '/api/library_tools/manual_identify/list'
      ? {
          action: 'preview',
          read_only: true,
          games: [{ name: 'Metroid', full_path: '/games/Metroid' }],
        }
      : { ok: true },
  )
  vi.mocked(confirmAction).mockResolvedValue(false)
  renderPage('/scan_management?active_tab=manual')
  await screen.findByRole('option', { name: 'Nintendo' })
  fireEvent.click(screen.getByRole('button', { name: 'List games to identify' }))
  await screen.findByRole('link', { name: 'Identify' })
  fireEvent.click(screen.getByRole('button', { name: 'Link existing game' }))
  fireEvent.click(screen.getByRole('button', { name: 'Search existing games' }))
  const hit = await screen.findByRole('button', { name: 'Metroid Prime · /games/Metroid Prime' })
  fireEvent.click(hit)
  const link = screen.getByRole('button', { name: 'Link selected game' })
  fireEvent.click(link)
  await waitFor(() =>
    expect(confirmAction).toHaveBeenCalledWith(
      expect.objectContaining({ confirmLabel: 'Link folder' }),
    ),
  )
  expect(postJson).not.toHaveBeenCalledWith(
    '/api/library_tools/link_existing_game',
    expect.anything(),
  )

  vi.mocked(confirmAction).mockResolvedValue(true)
  fireEvent.click(link)
  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/library_tools/link_existing_game', {
      game_uuid: 'game-1',
      full_disk_path: '/games/Metroid',
      library_uuid: 'lib-1',
    }),
  )
  expect(await screen.findByRole('status')).toHaveTextContent('Linked folder to Metroid Prime.')
  expect(screen.queryByRole('link', { name: 'Identify' })).not.toBeInTheDocument()
})
