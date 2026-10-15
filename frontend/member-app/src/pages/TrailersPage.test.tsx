import { vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TrailersPage } from './TrailersPage'
import * as trailersApi from '../api/trailers'
import { ShellHarness } from '../testShell'

vi.mock('../api/trailers', () => ({
  fetchTrailerFilters: vi.fn(),
  fetchRandomTrailer: vi.fn(),
  fetchAttractModeSettings: vi.fn(),
  saveAttractModePreferences: vi.fn(),
}))

const FILTER_OPTIONS = {
  libraries: [{ uuid: 'lib-1', name: 'Retro Shelf' }],
  genres: [{ id: 3, name: 'Shooter' }],
  themes: [{ id: 9, name: 'Horror' }],
  date_range: { min_year: 1993, max_year: 2024 },
}

beforeEach(() => {
  vi.mocked(trailersApi.fetchTrailerFilters).mockReset()
  vi.mocked(trailersApi.fetchRandomTrailer).mockReset()
  vi.mocked(trailersApi.fetchAttractModeSettings).mockReset()
  vi.mocked(trailersApi.saveAttractModePreferences).mockReset()
  vi.mocked(trailersApi.fetchTrailerFilters).mockResolvedValue(FILTER_OPTIONS)
})

test('shows loading then renders the random trailer', async () => {
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-1',
    game_name: 'Doom',
    video_url: 'https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0',
  })

  render(
    <ShellHarness>
      <TrailersPage />
    </ShellHarness>,
  )

  expect(screen.getByText(/Loading random trailer/)).toBeInTheDocument()

  expect(await screen.findByRole('heading', { name: 'Doom' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Doom' })).toHaveAttribute(
    'href',
    '/game_details/game-uuid-1',
  )

  const frame = screen.getByTitle('Game trailer')
  expect(frame.getAttribute('src')).toContain('https://www.youtube.com/embed/dQw4w9WgXcQ')
  expect(screen.queryByText(/Loading random trailer/)).not.toBeInTheDocument()
})

test('shows the no-results state when nothing matches', async () => {
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: false,
    message: 'No games with trailers found matching your filters',
  })

  render(
    <ShellHarness>
      <TrailersPage />
    </ShellHarness>,
  )

  expect(
    await screen.findByText('No games with trailers found matching your filters'),
  ).toBeInTheDocument()
  expect(screen.queryByTitle('Game trailer')).not.toBeInTheDocument()
  // Empty copy only — no admin “Add games” / Library CTA (Wishlist/Collections rhythm).
  expect(screen.queryByRole('link', { name: /library/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('shows structured empty for Backend no_trailers contract without a CTA', async () => {
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: false,
    empty: true,
    code: 'no_trailers',
    message: 'No trailers in your library yet.',
    cta: { id: 'library', label: 'Browse Library', href: '/library' },
  })

  render(
    <ShellHarness>
      <TrailersPage />
    </ShellHarness>,
  )

  expect(await screen.findByText('No trailers in your library yet.')).toBeInTheDocument()
  expect(screen.getByRole('status')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Browse Library/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByText(/unable to load/i)).not.toBeInTheDocument()
})

test('rejects a non-YouTube embed URL', async () => {
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-2',
    game_name: 'Sketchy',
    video_url: 'javascript:alert(1)',
  })

  render(
    <ShellHarness>
      <TrailersPage />
    </ShellHarness>,
  )

  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid video URL format')
  expect(screen.queryByTitle('Game trailer')).not.toBeInTheDocument()
})

test('shows an error with retry', async () => {
  const user = userEvent.setup()
  vi.mocked(trailersApi.fetchRandomTrailer)
    .mockRejectedValueOnce(new Error('boom'))
    .mockResolvedValueOnce({ has_videos: false, message: 'No games with trailers found' })

  render(
    <ShellHarness>
      <TrailersPage />
    </ShellHarness>,
  )

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load trailers.')
  await user.click(screen.getByRole('button', { name: 'Retry' }))

  expect(await screen.findByText('No games with trailers found')).toBeInTheDocument()
})

test('applies selected filters when asking for another trailer', async () => {
  const user = userEvent.setup()
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-3',
    game_name: 'Quake',
    video_url: 'https://www.youtube.com/embed/abc12345678?autoplay=1&rel=0',
  })

  render(
    <ShellHarness>
      <TrailersPage />
    </ShellHarness>,
  )

  await screen.findByRole('heading', { name: 'Quake' })

  await user.click(screen.getByRole('button', { name: 'Filters' }))
  await user.selectOptions(await screen.findByLabelText('Library'), 'lib-1')
  const genres = screen.getByRole('group', { name: 'Genre options' })
  await user.click(within(genres).getByRole('button', { name: 'Shooter' }))
  await user.click(screen.getByRole('button', { name: 'Apply' }))

  await waitFor(() => {
    expect(trailersApi.fetchRandomTrailer).toHaveBeenCalledTimes(2)
  })
  expect(trailersApi.fetchRandomTrailer).toHaveBeenLastCalledWith(
    expect.objectContaining({
      filters: expect.objectContaining({ library: 'lib-1', genres: ['3'] }),
    }),
  )
})

test('trailer genre and theme chips stay as drafts until Apply', async () => {
  const user = userEvent.setup()
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: false,
    message: 'No trailers match these filters',
  })

  render(
    <ShellHarness>
      <TrailersPage />
    </ShellHarness>,
  )

  await screen.findByText('No trailers match these filters')
  await user.click(screen.getByRole('button', { name: 'Filters' }))
  const genres = screen.getByRole('group', { name: 'Genre options' })
  const themes = screen.getByRole('group', { name: 'Theme options' })
  await user.click(within(genres).getByRole('button', { name: 'Shooter' }))
  await user.click(within(themes).getByRole('button', { name: 'Horror' }))

  expect(trailersApi.fetchRandomTrailer).toHaveBeenCalledTimes(1)
  expect(within(genres).getByRole('button', { name: 'Shooter' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(within(themes).getByRole('button', { name: 'Horror' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )

  await user.click(screen.getByRole('button', { name: 'Apply' }))
  await waitFor(() => expect(trailersApi.fetchRandomTrailer).toHaveBeenCalledTimes(2))
  expect(trailersApi.fetchRandomTrailer).toHaveBeenLastCalledWith(
    expect.objectContaining({ filters: expect.objectContaining({ genres: ['3'], themes: ['9'] }) }),
  )
})

test('another trailer keeps the player up while the next one loads', async () => {
  // UX-B6: "Another one" used to null the trailer, swap in a loading
  // paragraph, and shove the player off the page. The overlay sits on top
  // of the current frame instead (and is delayed, so this assertion is the
  // player staying, not a flash of overlay).
  const user = userEvent.setup()
  let releaseSecond: ((value: unknown) => void) | undefined
  vi.mocked(trailersApi.fetchRandomTrailer)
    .mockResolvedValueOnce({
      has_videos: true,
      game_uuid: 'game-uuid-1',
      game_name: 'Doom',
      video_url: 'https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0',
    })
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseSecond = resolve
        }),
    )

  render(
    <ShellHarness>
      <TrailersPage />
    </ShellHarness>,
  )
  await screen.findByRole('heading', { name: 'Doom' })
  await user.click(screen.getByRole('button', { name: 'Another one' }))

  expect(screen.getByRole('heading', { name: 'Doom' })).toBeInTheDocument()
  expect(screen.queryByText(/Loading random trailer/)).not.toBeInTheDocument()

  releaseSecond!({
    has_videos: true,
    game_uuid: 'game-uuid-3',
    game_name: 'Quake',
    video_url: 'https://www.youtube.com/embed/abc12345678?autoplay=1&rel=0',
  })
  expect(await screen.findByRole('heading', { name: 'Quake' })).toBeInTheDocument()
})

test('new chrome keeps the playing title as content, not as a page heading', async () => {
  // The h1 here was never page identity — it names the trailer now playing and
  // links to that game. Retiring it as a "page title" would delete real
  // information, so it becomes bar two's summary and stays a link.
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-1',
    game_name: 'Doom',
    video_url: 'https://www.youtube.com/embed/x',
  })

  render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <TrailersPage />
    </ShellHarness>,
  )

  const link = await screen.findByRole('link', { name: 'Doom' })
  expect(link).toHaveAttribute('href', '/game_details/game-uuid-1')
  expect(screen.queryByRole('heading', { name: 'Doom' })).toBeNull()
})

test('new chrome keeps every playback action reachable', async () => {
  const user = userEvent.setup()
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-1',
    game_name: 'Doom',
    video_url: 'https://www.youtube.com/embed/x',
  })

  render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <TrailersPage />
    </ShellHarness>,
  )
  await screen.findByRole('link', { name: 'Doom' })

  await user.click(screen.getByRole('button', { name: 'Another one' }))
  await waitFor(() => expect(trailersApi.fetchRandomTrailer).toHaveBeenCalledTimes(2))

  // Reachable, not necessarily on the bar. Four peer buttons was this page
  // inventing its own toolbar; "Another one" is the one pressed repeatedly and
  // stays visible, the once-a-session actions moved behind the overflow. The
  // assertion this test exists for is that none of them became unreachable.
  expect(screen.queryByRole('button', { name: 'Settings' })).toBeNull()
  await user.click(screen.getByRole('button', { name: /More/i }))
  expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
})

test('trailers shows exactly one Filters control under the new chrome', async () => {
  // The page's own toggle used to be suppressed with `hidden`, which did
  // nothing: `.od-trailers__filters` sets `display: flex`, and an author rule
  // beats the UA stylesheet's `[hidden]`. Both the page toggle and the context
  // bar's popover rendered — the duplication W27-F1 set out to remove.
  //
  // Counted by role rather than by class, because the defect was about what a
  // member can see and click, not which element carries which attribute.
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-1',
    game_name: 'Doom',
    video_url: 'https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0',
  })

  render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <TrailersPage />
    </ShellHarness>,
  )

  await screen.findByRole('button', { name: /^filters$/i })
  expect(screen.getAllByRole('button', { name: /^filters$/i })).toHaveLength(1)
})

test('new chrome fuses Filters, Another one, and More into one cluster', async () => {
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-1',
    game_name: 'Doom',
    video_url: 'https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0',
  })

  const { container } = render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <TrailersPage />
    </ShellHarness>,
  )
  await screen.findByRole('button', { name: /^filters$/i })

  const group = container.querySelector('.od-cbtn-group')
  expect(group).toBeTruthy()
  expect(
    within(group! as HTMLElement).getByRole('button', { name: /^filters$/i }),
  ).toBeInTheDocument()
  expect(
    within(group! as HTMLElement).getByRole('button', { name: 'Another one' }),
  ).toBeInTheDocument()
  expect(within(group! as HTMLElement).getByRole('button', { name: /^more$/i })).toBeInTheDocument()
})

test('Filters popover matches Library panel chrome', async () => {
  // Chromeless panel (no Filters/Done head), Apply/Clear fused at the top,
  // same `.library-filters` form Library uses — not a nested box under Done.
  const user = userEvent.setup()
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-1',
    game_name: 'Doom',
    video_url: 'https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0',
  })

  const { container } = render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <TrailersPage />
    </ShellHarness>,
  )
  await user.click(await screen.findByRole('button', { name: /^filters$/i }))

  const panel = container.querySelector('.od-pop__panel')
  expect(panel).toBeTruthy()
  expect(panel!.classList.contains('od-pop__panel--bare')).toBe(true)
  expect(within(panel! as HTMLElement).queryByText('Done')).toBeNull()
  expect(within(panel! as HTMLElement).getByRole('button', { name: 'Apply' })).toBeInTheDocument()
  expect(within(panel! as HTMLElement).getByRole('button', { name: 'Clear' })).toBeInTheDocument()
  expect(panel!.querySelector('.library-filters')).toBeTruthy()
  expect(panel!.querySelector('.library-filters__actions .od-cbtn-group')).toBeTruthy()
})

test('trailers keeps its own Filters toggle on the old chrome', async () => {
  // The other half of the contract: suppressing the page control must depend on
  // the new bar actually being there to own it.
  vi.mocked(trailersApi.fetchRandomTrailer).mockResolvedValue({
    has_videos: true,
    game_uuid: 'game-uuid-1',
    game_name: 'Doom',
    video_url: 'https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0',
  })

  render(
    <ShellHarness shell={{ enableNewChrome: false }}>
      <TrailersPage />
    </ShellHarness>,
  )

  expect(await screen.findByRole('button', { name: /^filters$/i })).toBeInTheDocument()
})
