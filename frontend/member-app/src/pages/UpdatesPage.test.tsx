import { vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { UpdatesPage } from './UpdatesPage'
import * as updatesApi from '../api/updates'
import * as clientCommands from '../api/clientCommands'
import * as calendarApi from '../api/calendar'
import * as downloadsApi from '../api/downloads'
import { ShellHarness } from '../testShell'

vi.mock('../api/updates', () => ({
  fetchUpdatesInbox: vi.fn(),
  fetchStoreSearch: vi.fn(),
  addWantedUpdate: vi.fn(),
  scanLibraryUpdates: vi.fn(),
}))

vi.mock('../api/clientCommands', () => ({
  queueClientCommand: vi.fn(),
}))

vi.mock('../api/calendar', () => ({
  fetchCalendar: vi.fn(),
}))

vi.mock('../api/downloads', () => ({
  initiateGameDownload: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(updatesApi.fetchUpdatesInbox).mockReset()
  vi.mocked(updatesApi.fetchStoreSearch).mockReset()
  vi.mocked(updatesApi.addWantedUpdate)?.mockReset?.()
  vi.mocked(updatesApi.scanLibraryUpdates).mockReset()
  vi.mocked(updatesApi.scanLibraryUpdates).mockResolvedValue({
    ok: true,
    checked: 0,
    behind_count: 0,
    behind: [],
    errors: [],
    remaining: 0,
  })
  vi.mocked(clientCommands.queueClientCommand).mockReset()
  vi.mocked(calendarApi.fetchCalendar).mockReset()
  vi.mocked(downloadsApi.initiateGameDownload).mockReset()
  vi.mocked(downloadsApi.initiateGameDownload).mockResolvedValue({})
  vi.mocked(calendarApi.fetchCalendar).mockResolvedValue({
    releases: [
      {
        igdb_id: 9,
        name: 'Soon Game',
        first_release_date: '2026-09-01',
        window: 'upcoming',
      },
    ],
  })
  vi.mocked(updatesApi.fetchUpdatesInbox).mockResolvedValue({
    items: [
      {
        uuid: 'game-1',
        name: 'Behind Game',
        freshness_status: 'behind',
        local_version: '1.0',
        remote_version_summary: 'STEAM: 1.1',
        updates_count: 1,
        client_connected: true,
        latest_update: {
          kind: 'update',
          uuid: 'upd-1',
          label: 'Update: patch.zip',
          download_url: '/download_other/update/game-1/upd-1',
        },
      },
    ],
  })
})

test('inbox shows apply action and queues companion update pack', async () => {
  const user = userEvent.setup()
  vi.mocked(clientCommands.queueClientCommand).mockResolvedValue({ ok: true })

  render(
    <MemoryRouter>
      <ShellHarness>
        <UpdatesPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  expect(await screen.findByText('Behind Game')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /Download update/i }))
  await waitFor(() => {
    expect(downloadsApi.initiateGameDownload).toHaveBeenCalledWith('game-1', {
      kind: 'update',
      versionUuid: 'upd-1',
    })
  })
  await user.click(screen.getByRole('button', { name: /Apply with companion/i }))
  await waitFor(() => {
    expect(clientCommands.queueClientCommand).toHaveBeenCalledWith('game-1', 'update', {
      kind: 'update',
      versionUuid: 'upd-1',
    })
  })
  expect(
    await screen.findByText((_, el) =>
      Boolean(
        el?.classList?.contains('od-updates__status') &&
        /queued for companion/i.test(el.textContent || ''),
      ),
    ),
  ).toBeInTheDocument()
})

test('manual Refresh shows brief feedback without wiping inbox', async () => {
  const user = userEvent.setup()
  let resolveInbox: ((value: any) => void) | undefined
  vi.mocked(updatesApi.fetchUpdatesInbox)
    .mockResolvedValueOnce({
      items: [
        {
          uuid: 'game-1',
          name: 'Behind Game',
          freshness_status: 'behind',
          local_version: '1.0',
          remote_version_summary: 'STEAM: 1.1',
          updates_count: 1,
          client_connected: false,
        },
      ],
    })
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveInbox = resolve
        }),
    )

  render(
    <MemoryRouter>
      <ShellHarness>
        <UpdatesPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  expect(await screen.findByText('Behind Game')).toBeInTheDocument()
  // Glyph-only control, and now the *only* refresh control on the page — its
  // accessible name has to carry what the word would have said.
  const refresh = screen.getByRole('button', {
    name: 'Check the library against store versions',
  })
  await user.click(refresh)

  // Scoped to the control's own row. The page carries a second `role="status"`
  // — the scan result line ("Checked N titles · …") — now that this one control
  // runs the probe, so an unscoped query matches two live regions. Both are
  // correct; this test is about the busy state on the heading row.
  //
  // Busy feedback, whichever half of the round trip is in flight: the probe
  // ("Checking library…") or the inbox re-read that follows it ("Refreshing…").
  // The point of the test is that there *is* feedback and the list survives it.
  const tools = refresh.closest('.od-updates__inbox-tools')
  expect(within(tools! as HTMLElement).getByRole('status')).toHaveTextContent(
    /Checking library|Refreshing/i,
  )
  expect(screen.getByText('Behind Game')).toBeInTheDocument()

  resolveInbox!({
    items: [
      {
        uuid: 'game-1',
        name: 'Behind Game',
        freshness_status: 'behind',
        local_version: '1.0',
        remote_version_summary: 'STEAM: 1.2',
        updates_count: 1,
        client_connected: false,
      },
    ],
  })

  await waitFor(() => {
    expect(screen.queryByText(/^(Refreshing|Checking library)…$/)).not.toBeInTheDocument()
  })
})

test('shows upcoming releases teaser with calendar link', async () => {
  render(
    <MemoryRouter>
      <ShellHarness>
        <UpdatesPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  expect(await screen.findByRole('heading', { name: /Upcoming releases/i })).toBeInTheDocument()
  expect(await screen.findByText('Soon Game')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Open calendar/i })).toHaveAttribute('href', '/calendar')
})

test('refresh and its timestamp sit on the inbox heading row', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <ShellHarness shell={{ enableNewChrome: true }}>
        <UpdatesPage />
      </ShellHarness>
    </MemoryRouter>,
  )
  await waitFor(() => expect(updatesApi.fetchUpdatesInbox).toHaveBeenCalled())

  expect(screen.queryByRole('heading', { name: 'Updates' })).toBeNull()

  // The refresh status is the only thing that says whether what you are
  // looking at is current, so it has to survive the move — losing it would
  // make a stale inbox indistinguishable from a fresh one. The control is a
  // symbol on the inbox heading now rather than a word in bar two, and the
  // timestamp reads *before* the glyph. Queried by role+name precisely so the
  // icon cannot ship without an accessible name.
  const refresh = await screen.findByRole('button', {
    name: 'Check the library against store versions',
  })
  expect(refresh.closest('.od-updates__inbox-tools')).not.toBeNull()
  await user.click(refresh)
  await waitFor(() => expect(screen.getByText(/^Updated /)).toBeInTheDocument())

  const tools = refresh.closest('.od-updates__inbox-tools')
  const stamp = tools!.querySelector('.od-updates__refresh-status')
  expect(stamp!.compareDocumentPosition(refresh) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

/**
 * The library sweep and the inbox re-read are **one** control now.
 *
 * They used to be two, side by side on the same rule, both reading as "refresh
 * this list" — the glyph re-read the stored inbox, the button ran a fresh probe
 * and *then* re-read the inbox itself. Nobody could be expected to know which
 * one they wanted, and the quiet one silently did less.
 *
 * They collapse into the glyph, wired to the probe, because the probe was
 * already the strict superset. This test keeps its original job — a press makes
 * a new probe happen, reports what is left, and refills the inbox — and only
 * changes which control it presses.
 */
test('the one refresh control probes the library and refills the inbox', async () => {
  const user = userEvent.setup()
  vi.mocked(updatesApi.scanLibraryUpdates).mockResolvedValue({
    ok: true,
    checked: 25,
    behind_count: 2,
    behind: [],
    errors: [],
    remaining: 387,
  })

  render(
    <MemoryRouter>
      <ShellHarness shell={{ enableNewChrome: true }}>
        <UpdatesPage />
      </ShellHarness>
    </MemoryRouter>,
  )
  await waitFor(() => expect(updatesApi.fetchUpdatesInbox).toHaveBeenCalled())
  const before = vi.mocked(updatesApi.fetchUpdatesInbox).mock.calls.length

  await user.click(screen.getByRole('button', { name: 'Check the library against store versions' }))

  // …and there is no second control that looks like it does the same thing.
  expect(screen.queryByRole('button', { name: /Check library for updates/i })).toBeNull()

  await waitFor(() => expect(updatesApi.scanLibraryUpdates).toHaveBeenCalled())
  // Says how much is left, so "press again" is a real instruction rather than
  // a guess about whether one press did the whole library.
  expect(await screen.findByText(/387 still to check/i)).toBeInTheDocument()
  await waitFor(() =>
    expect(vi.mocked(updatesApi.fetchUpdatesInbox).mock.calls.length).toBeGreaterThan(before),
  )
})

test('store search failure uses PageStatus', async () => {
  const user = userEvent.setup()
  vi.mocked(updatesApi.fetchStoreSearch).mockRejectedValue(new Error('upstream down'))

  render(
    <MemoryRouter>
      <ShellHarness>
        <UpdatesPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  await screen.findByText('Behind Game')
  await user.type(screen.getByLabelText(/Game name/i), 'Hades')
  await user.click(screen.getByRole('button', { name: /^Search$/i }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Store search failed: upstream down')
})
