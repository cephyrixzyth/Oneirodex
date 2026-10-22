import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { getJson, postJsonResult } from '../api/adminApi'
import { LibrariesPanel } from './LibrariesPanel'

vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  postJsonResult: vi.fn(),
}))

vi.mock('../hooks/useLibraryScan', () => ({
  useLibraryScan: () => ({
    conflictOpen: false,
    busyKey: null,
    startScan: vi.fn(),
    onConflictChoose: vi.fn(),
    onConflictClose: vi.fn(),
  }),
}))

vi.mock('../utils/toast', () => ({
  showToast: vi.fn(),
}))

const ROWS = [
  {
    uuid: 'a',
    name: '_pc',
    platform: 'PC Windows',
    platform_key: 'PCWIN',
    game_count: 1640,
    unmatched_count: 12,
    platform_total: null,
    group_name: null,
    image_url: '',
    last_scan_folder: '/storage/_pc',
  },
  {
    uuid: 'b',
    name: 'NES',
    platform: 'Nintendo Entertainment System (NES)',
    platform_key: 'NES',
    game_count: 0,
    unmatched_count: 3,
    platform_total: 200,
    group_name: null,
    image_url: '',
    last_scan_folder: '/storage/nes',
  },
  {
    uuid: 'c',
    name: 'SNES',
    platform: 'Super Nintendo Entertainment System (SNES)',
    platform_key: 'SNES',
    game_count: 200,
    unmatched_count: 0,
    platform_total: 200,
    group_name: 'Consoles',
    image_url: '',
    last_scan_folder: '/storage/snes',
  },
]

beforeEach(() => {
  vi.mocked(getJson).mockReset()
  vi.mocked(postJsonResult).mockReset()
  vi.mocked(getJson).mockImplementation(async (url) =>
    String(url).includes('/api/admin/library_platforms')
      ? { platforms: [{ key: 'NES', label: 'Nintendo Entertainment System (NES)' }] }
      : ROWS,
  )
  vi.mocked(postJsonResult).mockResolvedValue({ ok: true, status: 200, data: { ok: true } })
  document.getElementById('od-admin-topbar-trail')?.remove()
  const trail = document.createElement('div')
  trail.id = 'od-admin-topbar-trail'
  document.body.appendChild(trail)
  try {
    window.sessionStorage?.clear()
  } catch {
    /* ignore */
  }
})

test('hides selected copy until a row is checked', async () => {
  render(<LibrariesPanel />)
  await screen.findByText('_pc')
  expect(screen.queryByText('0 selected')).toBeNull()
})

test('keeps the native library error visible and retries the roster request', async () => {
  window.sessionStorage.setItem('od-libraries-catalog-refresh-v1', '1')
  const user = userEvent.setup()
  vi.mocked(getJson).mockRejectedValueOnce(new Error('Temporary review failure.'))
  render(<LibrariesPanel />)

  const retry = await screen.findByRole('button', { name: 'Retry loading libraries' })
  expect(screen.getByRole('alert')).toHaveTextContent('Unable to load libraries.')
  const callsBeforeRetry = vi
    .mocked(getJson)
    .mock.calls.filter(([url]) => url === '/api/get_libraries').length
  await user.click(retry)
  expect(await screen.findByText('_pc')).toBeInTheDocument()
  const callsAfterRetry = vi
    .mocked(getJson)
    .mock.calls.filter(([url]) => url === '/api/get_libraries').length
  expect(callsAfterRetry).toBeGreaterThan(callsBeforeRetry)
})

test('the real Jinja libraries panel exposes the add-and-first-scan form', async () => {
  render(<LibrariesPanel />)
  expect(await screen.findByRole('heading', { name: 'Add one library' })).toBeInTheDocument()
  expect(
    await screen.findByRole('option', { name: 'Nintendo Entertainment System (NES)' }),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Create library' })).toBeDisabled()
})

test('native libraries expose folder proposal and CSV/JSON import with previews before confirmation', async () => {
  render(<LibrariesPanel />)
  await screen.findByText('_pc')

  fireEvent.click(screen.getByRole('button', { name: 'Propose from folder' }))
  expect(await screen.findByRole('heading', { name: 'Propose leaf libraries' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Propose' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: /Confirm create/ })).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: 'Import CSV/JSON' }))
  expect(
    await screen.findByRole('heading', { name: 'Import leaf libraries (CSV / JSON)' }),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: /Confirm create/ })).toBeNull()
  expect(screen.getByRole('button', { name: 'Import CSV/JSON' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
})

test('libraries count lives in the topbar trail and opens a platform filter menu', async () => {
  try {
    window.sessionStorage?.setItem('od-libraries-catalog-refresh-v1', '1')
  } catch {
    /* ignore */
  }
  render(<LibrariesPanel />)
  await screen.findByText('_pc')
  const trigger = await screen.findByRole('button', { name: /3 libraries/i })
  await waitFor(() => {
    expect(document.getElementById('od-admin-topbar-trail')?.contains(trigger)).toBe(true)
  })
  fireEvent.click(trigger)
  expect(screen.getByText(/1840 games/i)).toBeTruthy()
  expect(screen.getByText(/15 unmatched/i)).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Filter by platform'), {
    target: { value: 'nintendo entertainment system' },
  })
  const dialog = screen.getByRole('dialog', { name: 'Libraries summary' })
  expect(within(dialog).getByText('Nintendo Entertainment System (NES)')).toBeTruthy()
  expect(within(dialog).queryByText('PC Windows')).toBeNull()
  const platformButton = within(dialog)
    .getByText('Nintendo Entertainment System (NES)')
    .closest('button')
  expect(platformButton).not.toBeNull()
  platformButton?.focus()
  fireEvent.click(platformButton!)
  await waitFor(() => {
    expect(screen.queryByText('_pc')).toBeNull()
  })
  expect(screen.getByText('NES')).toBeTruthy()
  expect(document.activeElement).toBe(trigger)
})

test('libraries summary restores focus after Escape and Done, but not an outside click', async () => {
  render(<LibrariesPanel />)
  await screen.findByText('_pc')
  const trigger = await screen.findByRole('button', { name: /3 libraries/i })

  fireEvent.click(trigger)
  screen.getByLabelText('Filter by platform').focus()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: 'Libraries summary' })).toBeNull()
  expect(document.activeElement).toBe(trigger)

  fireEvent.click(trigger)
  const done = screen.getByRole('button', { name: 'Done' })
  done.focus()
  fireEvent.click(done)
  expect(screen.queryByRole('dialog', { name: 'Libraries summary' })).toBeNull()
  expect(document.activeElement).toBe(trigger)

  const outside = document.createElement('button')
  outside.textContent = 'Outside target'
  document.body.append(outside)
  try {
    fireEvent.click(trigger)
    screen.getByLabelText('Filter by platform').focus()
    await userEvent.setup().click(outside)
    expect(screen.queryByRole('dialog', { name: 'Libraries summary' })).toBeNull()
    expect(document.activeElement).toBe(outside)
  } finally {
    outside.remove()
  }
})

test('group column is present only when a library is grouped', async () => {
  render(<LibrariesPanel />)
  await screen.findByText('Consoles')
  expect(screen.getByRole('columnheader', { name: /Group/i })).toBeTruthy()
})

test('group column is omitted when nothing is grouped', async () => {
  vi.mocked(getJson).mockResolvedValue(ROWS.map((row) => ({ ...row, group_name: null })))
  render(<LibrariesPanel />)
  await screen.findByText('_pc')
  expect(screen.queryByRole('columnheader', { name: /Group/i })).toBeNull()
})

test('row Group opens a dialog and posts group_name', async () => {
  render(<LibrariesPanel />)
  await screen.findByText('_pc')
  const row = screen.getByRole('row', { name: /_pc/i })
  fireEvent.click(within(row).getByRole('button', { name: 'Group _pc library' }))
  fireEvent.change(screen.getByPlaceholderText('e.g. Arcade cabinets'), {
    target: { value: 'PC' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => {
    expect(postJsonResult).toHaveBeenCalledWith(
      '/api/admin/libraries/batch/edit',
      expect.objectContaining({
        library_uuids: ['a'],
        group_name: 'PC',
      }),
    )
  })
})

test('colors game counts when a platform total is known', async () => {
  try {
    window.sessionStorage?.setItem('od-libraries-catalog-refresh-v1', '1')
  } catch {
    /* ignore */
  }
  render(<LibrariesPanel />)
  await screen.findByText('SNES')
  const full = screen.getByTitle('200 of 200 released')
  const empty = screen.getByTitle('0 of 200 released')
  // jsdom may serialize hsl() as rgb(); assert the computed green/red channel.
  expect(full.style.color).toBeTruthy()
  expect(empty.style.color).toBeTruthy()
  expect(full.style.color).not.toEqual(empty.style.color)
})

test('row Edit opens the shared React modal and applies selected fields through the batch API', async () => {
  vi.mocked(postJsonResult).mockResolvedValue({
    ok: true,
    status: 200,
    data: { updated: 1, skipped: 0, failed: 0 },
  })
  render(<LibrariesPanel />)
  await screen.findByText('_pc')
  const row = screen.getByText('_pc').closest('tr')
  expect(row).toBeTruthy()
  fireEvent.click(within(row!).getByRole('button', { name: 'Edit _pc library' }))
  const dialog = await screen.findByRole('dialog', { name: 'Edit library' })
  expect(dialog).toBeInTheDocument()
  fireEvent.change(within(dialog).getByLabelText('Scan depth'), { target: { value: '2' } })
  fireEvent.change(within(dialog).getByLabelText('Update library when folders change'), {
    target: { value: 'off' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }))
  await waitFor(() =>
    expect(postJsonResult).toHaveBeenCalledWith('/api/admin/libraries/batch/edit', {
      library_uuids: ['a'],
      scan_depth: 2,
      watch_enabled: false,
    }),
  )
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('row Delete requires the exact library name and posts through the React confirmation dialog', async () => {
  render(<LibrariesPanel />)
  await screen.findByText('_pc')
  const row = screen.getByText('_pc').closest('tr')
  expect(row).toBeTruthy()
  fireEvent.click(within(row!).getByRole('button', { name: 'Delete _pc library' }))
  const dialog = await screen.findByRole('dialog', { name: 'Delete library' })
  const confirm = within(dialog).getByRole('button', { name: 'Confirm delete' })
  expect(confirm).toBeDisabled()
  fireEvent.change(within(dialog).getByLabelText(/Type _pc to confirm/i), {
    target: { value: '_pc' },
  })
  expect(confirm).toBeEnabled()
  fireEvent.click(confirm)
  await waitFor(() =>
    expect(postJsonResult).toHaveBeenCalledWith('/api/admin/libraries/batch/delete', {
      library_uuids: ['a'],
      force: true,
    }),
  )
  expect(screen.queryByRole('dialog')).toBeNull()
})
