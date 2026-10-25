import { vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DupeGlance } from './DupeGlance'
import { getJson, postJson } from '../api/adminApi'

vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(getJson).mockReset()
  vi.mocked(postJson).mockReset()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 1,
      folder_path: '/games/Celeste',
      status: 'Duplicate',
      library_name: 'PC',
      platform_name: 'PCWIN',
      library_uuid: 'lib-1',
      platform_id: 6,
      match_reason: 'Same IGDB id as existing title',
    },
    {
      id: 2,
      folder_path: '/games/3DSenVR',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      library_uuid: 'lib-1',
      platform_id: 6,
    },
  ])
  vi.mocked(postJson).mockResolvedValue({ changed_count: 1, kept_count: 0 })
})

/** Rows plus the served bad-match vocabulary (UX-C5). */
function mockWithBadMatch(rowOverrides = {}) {
  const reasons = [
    { id: 'wrong_game', label: 'Wrong game entirely' },
    { id: 'duplicate_of_other', label: 'Duplicate of another entry' },
    { id: 'other', label: 'Other' },
  ]
  vi.mocked(getJson).mockImplementation(async (url: any) => {
    if (String(url).includes('/api/unmatched/bad_match_reasons')) return { ok: true, reasons }
    if (String(url).includes('/api/unmatched_folders')) {
      return [
        {
          id: 1,
          folder_path: '/games/Celeste',
          status: 'Duplicate',
          library_name: 'PC',
          platform_name: 'PCWIN',
          library_uuid: 'lib-1',
          platform_id: 6,
          match_reason: 'Same IGDB id as existing title',
          ...rowOverrides,
        },
      ]
    }
    return []
  })
}

test('flagging a bad match posts the reason', async () => {
  const user = userEvent.setup()
  mockWithBadMatch()
  render(<DupeGlance onOpenPath={() => {}} />)
  await screen.findByText('/games/Celeste')

  const picker = await screen.findByLabelText('Flag bad match for /games/Celeste')
  await user.selectOptions(picker, 'wrong_game')

  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/unmatched/1/bad_match', { reason: 'wrong_game' }),
  )
})

test('"other" asks for a note before posting, because the API requires one', async () => {
  const user = userEvent.setup()
  mockWithBadMatch()
  render(<DupeGlance onOpenPath={() => {}} />)
  await screen.findByText('/games/Celeste')

  await user.selectOptions(
    await screen.findByLabelText('Flag bad match for /games/Celeste'),
    'other',
  )
  // Nothing posted yet — a bare "other" is a shrug, and the API rejects it.
  expect(postJson).not.toHaveBeenCalled()

  await user.type(screen.getByLabelText('Bad match note'), 'Matched the soundtrack')
  await user.click(screen.getByRole('button', { name: 'Save note' }))

  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/unmatched/1/bad_match', {
      reason: 'other',
      note: 'Matched the soundtrack',
    }),
  )
})

test('an existing flag is shown and can be cleared', async () => {
  const user = userEvent.setup()
  mockWithBadMatch({ bad_match_reason: 'wrong_game', bad_match_note: null })
  render(<DupeGlance onOpenPath={() => {}} />)

  expect(await screen.findByText(/Bad match: Wrong game entirely/)).toBeInTheDocument()

  await user.selectOptions(screen.getByLabelText('Flag bad match for /games/Celeste'), '')
  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/unmatched/1/bad_match', { reason: null }),
  )
})

test('DupeGlance sort buttons toggle Folder sort direction', async () => {
  const user = userEvent.setup()
  render(<DupeGlance onOpenPath={() => {}} />)
  await waitFor(() => expect(screen.getByText('/games/Celeste')).toBeTruthy())
  const folderSort = screen.getByRole('button', { name: 'Folder ↑' })
  expect(folderSort.getAttribute('aria-pressed')).toBe('true')
  await user.click(folderSort)
  expect(screen.getByRole('button', { name: 'Folder ↓' })).toBeTruthy()
  await user.click(screen.getByRole('button', { name: 'Status' }))
  expect(screen.getByRole('button', { name: 'Status ↑' }).getAttribute('aria-pressed')).toBe('true')
})

test('DupeGlance lists duplicates, match reason, and open-path callback', async () => {
  const user = userEvent.setup()
  const onOpenPath = vi.fn()
  render(<DupeGlance onOpenPath={onOpenPath} />)

  expect(await screen.findByRole('heading', { name: 'Dupe glance' })).toBeInTheDocument()
  expect(screen.getByText('/games/Celeste')).toBeInTheDocument()
  expect(screen.getByText('Same IGDB id as existing title')).toBeInTheDocument()
  expect(screen.queryByText('/games/3DSenVR')).toBeNull()

  await user.click(screen.getByRole('button', { name: 'Open path' }))
  expect(onOpenPath).toHaveBeenCalledWith(
    expect.objectContaining({
      path: '/games/Celeste',
      matchReason: 'Same IGDB id as existing title',
    }),
  )
})

test('DupeGlance surfaces fix log success from reclassify', async () => {
  const user = userEvent.setup()
  render(<DupeGlance onOpenPath={() => {}} />)

  await screen.findByRole('heading', { name: 'Dupe glance' })
  await user.click(screen.getByRole('button', { name: 'Fix false duplicates' }))

  await waitFor(() => {
    expect(postJson).toHaveBeenCalledWith('/api/unmatched_folders/reclassify_duplicates', {})
  })
  expect(await screen.findByText(/Reclassified 1 · kept 0 as duplicate/i)).toBeInTheDocument()
})

test('DupeGlance Mark as Emulator calls mark_kind and catalogs without IGDB', async () => {
  const user = userEvent.setup()
  vi.mocked(postJson).mockImplementation(async (url: any) => {
    if (String(url).includes('mark_kind')) {
      return { ok: true, name: '3DSenVR', item_kind: 'emulator', game_uuid: 'g-1' }
    }
    return { changed_count: 0, kept_count: 0 }
  })
  vi.mocked(getJson)
    .mockResolvedValueOnce([
      {
        id: 2,
        folder_path: '/games/3DSenVR',
        status: 'Unmatched',
        library_name: 'PC',
        platform_name: 'PCWIN',
      },
    ])
    .mockResolvedValueOnce([])

  render(<DupeGlance onOpenPath={() => {}} />)

  await screen.findByRole('heading', { name: 'Dupe glance' })
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText('/games/3DSenVR')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Fix search' })).toHaveAttribute(
    'href',
    '/add_game_manual?full_disk_path=%2Fgames%2F3DSenVR&library_uuid=&name=3DSenVR&platform_name=PCWIN&platform_id=&from_unmatched=true',
  )

  await user.click(screen.getByRole('button', { name: 'Mark as Emulator' }))

  await waitFor(() => {
    expect(postJson).toHaveBeenCalledWith('/api/unmatched_folders/2/mark_kind', {
      item_kind: 'emulator',
      name: '3DSenVR',
    })
  })
  expect(
    await screen.findByText(/Cataloged “3DSenVR” as Emulator \(no IGDB game match\)/i),
  ).toBeInTheDocument()
})

test('DupeGlance shows honest error when mark_kind fails', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 9,
      folder_path: '/games/SomeTool',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
    },
  ])
  vi.mocked(postJson).mockRejectedValue(new Error('Unmatched folder not found'))

  render(<DupeGlance onOpenPath={() => {}} />)
  await screen.findByRole('heading', { name: 'Dupe glance' })
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  await user.click(await screen.findByRole('button', { name: 'Mark as Utility' }))

  expect(await screen.findByText(/Unmatched folder not found/i)).toBeInTheDocument()
})

test('DupeGlance shows suggested_kind chip and pre-biases Mark as… when present', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 7,
      folder_path: '/games/3DSenVR',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      suggested_kind: 'emulator',
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await screen.findByRole('heading', { name: 'Dupe glance' })
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')

  expect(await screen.findByText(/Suggested Emulator/i)).toBeInTheDocument()
  const markButtons = screen.getAllByRole('button', { name: /Mark as /i })
  expect(markButtons[0]).toHaveTextContent('Mark as Emulator')
  expect(markButtons[0].className).toMatch(/is-suggested/)
})

test('DupeGlance tolerates missing suggested_kind without crashing', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 8,
      folder_path: '/games/PlainFolder',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      suggested_kind: null,
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText('/games/PlainFolder')).toBeInTheDocument()
  expect(screen.queryByText(/Suggested /i)).not.toBeInTheDocument()
})

test('DupeGlance shows match_score beside Why unmatched? when present', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 14,
      folder_path: '/games/ScoredMiss',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      why_unmatched: 'Title below auto-match threshold.',
      match_score: 0.42,
      suggested_kind: null,
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Why unmatched\?/i)).toBeInTheDocument()
  expect(screen.getByTitle('Match confidence score')).toHaveTextContent('0.42')
  expect(screen.getByText(/Title below auto-match threshold\./i)).toBeInTheDocument()
})

test('DupeGlance omits match_score chip when null', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 15,
      folder_path: '/games/NoScore',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      why_unmatched: 'No candidates.',
      match_score: null,
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Why unmatched\?/i)).toBeInTheDocument()
  expect(screen.queryByTitle('Match confidence score')).not.toBeInTheDocument()
})

test('DupeGlance shows Why unmatched? from why_unmatched when present', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 11,
      folder_path: '/games/MysterySoft',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      why_unmatched: 'No IGDB hit; Steam software candidate looks like an emulator.',
      suggested_kind: 'emulator',
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Why unmatched\?/i)).toBeInTheDocument()
  expect(
    screen.getByText(/No IGDB hit; Steam software candidate looks like an emulator\./i),
  ).toBeInTheDocument()
  expect(screen.getByText(/Suggested Emulator/i)).toBeInTheDocument()
})

test('DupeGlance builds Why unmatched? from match_reason + suggested_kind when summary absent', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 12,
      folder_path: '/games/NearMiss',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      match_reason: 'title_below_threshold',
      suggested_kind: null,
      why_unmatched: null,
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Why unmatched\?/i)).toBeInTheDocument()
  expect(
    screen.getByText(/folder title differs too much to auto-mark as duplicate/i),
  ).toBeInTheDocument()
})

test('DupeGlance tolerates null why fields without crashing', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 13,
      folder_path: '/games/EmptyWhy',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      match_reason: null,
      why_unmatched: null,
      suggested_kind: null,
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText('/games/EmptyWhy')).toBeInTheDocument()
  expect(screen.getByText(/Why unmatched\?/i)).toBeInTheDocument()
  expect(screen.getByText(/Could not auto-match to IGDB/i)).toBeInTheDocument()
})

test('DupeGlance shows ordered transform trail when transforms present', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 21,
      folder_path: '/games/Some Game (Repack) v1.2',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      why_unmatched: 'No IGDB hit after peels.',
      transforms: [
        {
          stage: 'A1',
          before: 'Some Game (Repack) v1.2',
          after: 'Some Game v1.2',
          reason: 'scene_repack_brackets',
        },
        {
          stage: 'A6',
          before: 'Some Game v1.2',
          after: 'Some Game',
          reason: 'version_access_tails',
        },
      ],
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Why unmatched\?/i)).toBeInTheDocument()
  expect(screen.getByText(/No IGDB hit after peels\./i)).toBeInTheDocument()
  const summary = screen.getByText(/Name transform trail \(2\)/i)
  expect(summary).toBeInTheDocument()
  await user.click(summary)
  const trail = summary.closest('details')
  expect(trail).not.toBeNull()
  expect(trail!.querySelector('.od-dupe-glance__transform-list')).not.toBeNull()
  const steps = trail!.querySelectorAll('.od-dupe-glance__transform-step')
  expect(steps).toHaveLength(2)
  expect(steps[0]).toHaveTextContent(/A1/)
  expect(steps[0]).toHaveTextContent('Some Game (Repack) v1.2')
  expect(steps[0]).toHaveTextContent('Some Game v1.2')
  expect(steps[0]).toHaveTextContent(/scene_repack_brackets/)
  expect(steps[1]).toHaveTextContent(/A6/)
  expect(steps[1]).toHaveTextContent('Some Game v1.2')
  expect(steps[1]).toHaveTextContent('Some Game')
  expect(steps[1]).toHaveTextContent(/version_access_tails/)
})

test('DupeGlance soft-degrades when transforms missing (mid-rollout)', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 22,
      folder_path: '/games/NoTrailYet',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      why_unmatched: 'Still waiting on trail field.',
      // transforms omitted on purpose
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Why unmatched\?/i)).toBeInTheDocument()
  expect(screen.getByText(/Still waiting on trail field\./i)).toBeInTheDocument()
  expect(screen.queryByText(/Name transform trail/i)).not.toBeInTheDocument()
})

test('DupeGlance soft-degrades when transforms is empty array', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 23,
      folder_path: '/games/EmptyTrail',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      why_unmatched: 'Clean basename; no peels.',
      transforms: [],
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Clean basename; no peels\./i)).toBeInTheDocument()
  expect(screen.queryByText(/Name transform trail/i)).not.toBeInTheDocument()
})

test('DupeGlance shows Stage E propose-only chip and expandable candidates', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 31,
      folder_path: '/games/Doom',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      why_unmatched: 'No IGDB hit after Stage D.',
      stage_e_candidates: [
        {
          source: 'mobygames',
          id: '42',
          name: 'Doom',
          url: 'https://www.mobygames.com/game/42',
          match_mode: 'moby_exact',
          propose_only: true,
          identify_path: 'stage_e',
        },
      ],
      stage_e: {
        match_reason: 'stage_e_moby_exact',
        identify_path: 'stage_e',
        skipped: ['tgdb_pc_skipped'],
        propose_only: true,
      },
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Why unmatched\?/i)).toBeInTheDocument()
  expect(screen.getByText(/Stage E · propose only · MobyGames/i)).toBeInTheDocument()
  const summary = screen.getByText(/Stage E candidates \(1\)/i)
  expect(summary).toBeInTheDocument()
  await user.click(summary)
  expect(screen.getByText(/Catalog hints only — Identify to apply/i)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Doom' })).toHaveAttribute(
    'href',
    'https://www.mobygames.com/game/42',
  )
  expect(screen.getByText('Exact')).toBeInTheDocument()
})

test('DupeGlance soft-degrades Stage E when fields absent (mid-rollout)', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 32,
      folder_path: '/games/NoStageEYet',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      why_unmatched: 'Legacy unmatched row.',
      suggested_candidate_name: 'Maybe Soft Hint',
      // stage_e* omitted on purpose
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText(/Legacy unmatched row\./i)).toBeInTheDocument()
  expect(screen.queryByText(/Stage E/i)).not.toBeInTheDocument()
  expect(screen.queryByText(/Stage E candidates/i)).not.toBeInTheDocument()
})

test('normalizeTransforms ignores malformed steps and keeps order', async () => {
  const { normalizeTransforms } = await import('./DupeGlance')
  expect(normalizeTransforms(null)).toEqual([])
  expect(normalizeTransforms({})).toEqual([])
  expect(
    normalizeTransforms({
      transforms: [
        null,
        { stage: 'A0', before: 'raw/path', after: 'raw', reason: 'basename_trim' },
        { stage: 'A7', before: 'raw', after: 'Raw', reason: 'title_case' },
        'skip-me',
      ],
    }),
  ).toEqual([
    { stage: 'A0', before: 'raw/path', after: 'raw', reason: 'basename_trim' },
    { stage: 'A7', before: 'raw', after: 'Raw', reason: 'title_case' },
  ])
})

test('DupeGlance Backfill kind hints confirms then posts and shows count', async () => {
  const user = userEvent.setup()
  vi.mocked(postJson).mockImplementation(async (url: any) => {
    if (String(url).includes('backfill_suggested_kind')) {
      return { ok: true, scanned: 12, updated: 4, skipped_no_sidecar: 7, skipped_empty_hint: 1 }
    }
    return { changed_count: 0, kept_count: 0 }
  })

  render(<DupeGlance onOpenPath={() => {}} />)
  await screen.findByRole('heading', { name: 'Dupe glance' })
  await user.click(screen.getByRole('button', { name: 'Backfill kind hints' }))
  // The house dialog, not window.confirm (UID-042) — its named button commits.
  await user.click(await screen.findByRole('button', { name: 'Fill in hints' }))

  await waitFor(() => {
    expect(postJson).toHaveBeenCalledWith('/api/unmatched_folders/backfill_suggested_kind', {})
  })
  expect(
    await screen.findByText(/Kind hints updated 4 of 12 scanned · 7 without proposal/i),
  ).toBeInTheDocument()
})

test('DupeGlance Backfill kind hints aborts when confirm is cancelled', async () => {
  const user = userEvent.setup()

  render(<DupeGlance onOpenPath={() => {}} />)
  await screen.findByRole('heading', { name: 'Dupe glance' })
  await user.click(screen.getByRole('button', { name: 'Backfill kind hints' }))
  await user.click(await screen.findByRole('button', { name: /^cancel$/i }))

  expect(postJson).not.toHaveBeenCalledWith(
    '/api/unmatched_folders/backfill_suggested_kind',
    expect.anything(),
  )
})

test('DupeGlance shows side-by-side compare for matched_game Duplicate rows', async () => {
  vi.mocked(getJson).mockImplementation(async (url: any) => {
    if (String(url).includes('/duplicates')) {
      return {
        duplicates: [
          {
            id: 1,
            candidates: [
              {
                uuid: 'game-celeste',
                name: 'Celeste',
                path: '/library/Celeste',
                cover_url: '/covers/celeste.jpg',
                match_score: 0.98,
              },
            ],
          },
        ],
      }
    }
    return [
      {
        id: 1,
        folder_path: '/games/Celeste',
        status: 'Duplicate',
        library_name: 'PC',
        platform_name: 'PCWIN',
        matched_game_uuid: 'game-celeste',
        match_reason: 'title_vs_folder',
      },
    ]
  })

  render(<DupeGlance onOpenPath={() => {}} />)
  expect(await screen.findByLabelText(/Duplicate side-by-side comparison/i)).toBeInTheDocument()
  expect(screen.getByText('This folder')).toBeInTheDocument()
  expect(screen.getByText('Library game')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Celeste' })).toHaveAttribute(
    'href',
    '/game_details/game-celeste',
  )
  expect(screen.getByText('/games/Celeste')).toBeInTheDocument()
  expect(screen.getByText('/library/Celeste')).toBeInTheDocument()
  // Size/Date honest empties until Backend enriches payload
  const empties = screen.getAllByTitle('Not provided by API yet')
  expect(empties.length).toBeGreaterThanOrEqual(4)
  expect(screen.getByTitle('Match confidence score')).toHaveTextContent('0.98')
  expect(screen.getByRole('button', { name: 'Merge' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Keep' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Ignore' })).toBeInTheDocument()
})

test('DupeGlance shows size and date when API provides them', async () => {
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 1,
      folder_path: '/games/Celeste',
      status: 'Duplicate',
      library_name: 'PC',
      platform_name: 'PCWIN',
      size_bytes: 2048,
      folder_mtime: '2024-03-01T10:00:00Z',
      matched_game: {
        uuid: 'game-celeste',
        name: 'Celeste',
        path: '/library/Celeste',
        size_bytes: 4096,
        date_identified: '2023-12-15T09:00:00Z',
        match_score: 0.99,
      },
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  expect(await screen.findByLabelText(/Duplicate side-by-side comparison/i)).toBeInTheDocument()
  expect(screen.getByText('2 KB')).toBeInTheDocument()
  expect(screen.getByText('4 KB')).toBeInTheDocument()
  expect(screen.getAllByText(/2024|2023/).length).toBeGreaterThanOrEqual(2)
})

test('DupeGlance Merge posts fix action', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 1,
      folder_path: '/games/Celeste',
      status: 'Duplicate',
      library_name: 'PC',
      platform_name: 'PCWIN',
      matched_game: {
        uuid: 'game-celeste',
        name: 'Celeste',
        path: '/library/Celeste',
      },
    },
  ])
  vi.mocked(postJson).mockResolvedValue({
    ok: true,
    action: 'merge',
    folder_path: '/games/Celeste',
  })

  render(<DupeGlance onOpenPath={() => {}} />)
  await screen.findByLabelText(/Duplicate side-by-side comparison/i)
  await user.click(screen.getByRole('button', { name: 'Merge' }))

  await waitFor(() => {
    expect(postJson).toHaveBeenCalledWith('/api/unmatched_folders/1/fix', { action: 'merge' })
  })
  expect(await screen.findByText(/Merged · \/games\/Celeste/i)).toBeInTheDocument()
})

test('DupeGlance shows Search name when soft name differs from on-disk basename', async () => {
  const user = userEvent.setup()
  vi.mocked(getJson).mockResolvedValue([
    {
      id: 42,
      folder_path: '/games/Celeste_v1.4.0',
      search_name: 'Celeste',
      status: 'Unmatched',
      library_name: 'PC',
      platform_name: 'PCWIN',
      library_uuid: 'lib-1',
      platform_id: 6,
    },
  ])

  render(<DupeGlance onOpenPath={() => {}} />)
  await screen.findByRole('heading', { name: 'Dupe glance' })
  await user.selectOptions(screen.getByLabelText(/status/i), 'Unmatched')
  expect(await screen.findByText('Search name')).toBeInTheDocument()
  expect(screen.getByText(/On disk: Celeste_v1\.4\.0/)).toBeInTheDocument()
  expect(screen.queryByText('Amend naming')).toBeNull()
  expect(screen.getByRole('link', { name: 'Fix search' }).getAttribute('title')).toMatch(
    /uses Search name when set/i,
  )
})
