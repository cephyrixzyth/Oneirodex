import { vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { NewsPage } from './NewsPage'
import * as announcementsApi from '../api/announcements'
import * as freeGamesApi from '../api/freeGames'
import * as gamingNewsApi from '../api/gamingNews'
import { ShellHarness } from '../testShell'

vi.mock('../api/announcements', () => ({
  fetchAnnouncements: vi.fn(),
}))

vi.mock('../api/freeGames', () => ({
  fetchFreeGames: vi.fn(),
  claimFreeGameAssist: vi.fn(),
}))

vi.mock('../api/gamingNews', () => ({
  fetchGamingNews: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(announcementsApi.fetchAnnouncements).mockReset()
  vi.mocked(freeGamesApi.fetchFreeGames).mockReset()
  vi.mocked(freeGamesApi.claimFreeGameAssist).mockReset()
  vi.mocked(gamingNewsApi.fetchGamingNews).mockReset()
  vi.mocked(freeGamesApi.fetchFreeGames).mockResolvedValue({ items: [] })
  vi.mocked(gamingNewsApi.fetchGamingNews).mockResolvedValue({ items: [] })
  window.location.hash = ''
  window.localStorage.removeItem('od.news.layout')
})

test('lists announcement cards from API', async () => {
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({
    announcements: [
      {
        id: 1,
        title: 'Welcome',
        body: 'Hello members',
        created_at: '2026-07-01T12:00:00+00:00',
      },
    ],
  })

  render(
    <ShellHarness>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )

  expect(screen.getByRole('status', { busy: true })).toBeInTheDocument()
  expect(await screen.findByText('Welcome')).toBeInTheDocument()
  expect(screen.getByText('Hello members')).toBeInTheDocument()
  expect(
    screen.getByText(
      (_, el) =>
        el?.tagName === 'TIME' && el.getAttribute('dateTime') === '2026-07-01T12:00:00+00:00',
    ),
  ).toBeInTheDocument()
})

test('the admin section stays off the combined view when there is nothing in it', async () => {
  // `announcements` is an array, so the old `announcements &&` was true when
  // empty and rendered a heading, a zero count and "No announcements yet." —
  // a permanent empty panel holding a column beside the two sections that
  // always have content.
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })

  render(
    <ShellHarness>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )

  expect(await screen.findByRole('heading', { name: 'Free now' })).toBeInTheDocument()
  expect(screen.queryByText('No announcements yet.')).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'From your admins' })).not.toBeInTheDocument()
})

test('the admin tab still says so when there are no announcements', async () => {
  // On its own tab the section *is* the page, so silence would read as a
  // failed load rather than an empty one.
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })

  render(
    <ShellHarness>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )

  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /Admins/ }))

  expect(await screen.findByText('No announcements yet.')).toBeInTheDocument()
})

test('keeps announcements when gaming news fails', async () => {
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({
    announcements: [
      {
        id: 2,
        title: 'Maintenance',
        body: 'Tonight',
        created_at: '2026-07-02T12:00:00+00:00',
      },
    ],
  })
  vi.mocked(gamingNewsApi.fetchGamingNews).mockRejectedValue(new Error('rss down'))

  render(
    <ShellHarness>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )

  expect(await screen.findByText('Maintenance')).toBeInTheDocument()
  expect(screen.queryByText('Unable to load news.')).not.toBeInTheDocument()
  expect(screen.getByText('No external headlines available right now.')).toBeInTheDocument()
})

test('section tabs filter free offers without a long scroll dump', async () => {
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })
  vi.mocked(freeGamesApi.fetchFreeGames).mockResolvedValue({
    items: [
      {
        id: 9,
        store: 'steam',
        external_id: 'abc',
        title: 'Free Space Adventure',
        description: 'Grab it while it lasts',
        links: { https: 'https://example.test/claim' },
        connected: false,
      },
    ],
  })
  vi.mocked(gamingNewsApi.fetchGamingNews).mockResolvedValue({
    items: [{ url: 'https://example.test/h1', title: 'Industry headline', source: 'Wire' }],
  })

  const user = userEvent.setup()
  render(
    <ShellHarness>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )

  expect(await screen.findByText('Free Space Adventure')).toBeInTheDocument()
  expect(screen.getByText('Industry headline')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Free now' }))
  expect(screen.getByText('Free Space Adventure')).toBeInTheDocument()
  expect(screen.queryByText('Industry headline')).not.toBeInTheDocument()
  expect(screen.queryByText('No announcements yet.')).not.toBeInTheDocument()
})

test('News layout smoke: hero strip and magazine densify', async () => {
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({
    announcements: [
      {
        id: 1,
        title: 'Household note',
        body: 'Servers stay up this weekend.',
        created_at: '2026-07-28T12:00:00+00:00',
      },
      {
        id: 2,
        title: 'Second note',
        body: 'Backup finished.',
        created_at: '2026-07-20T12:00:00+00:00',
      },
    ],
  })
  vi.mocked(gamingNewsApi.fetchGamingNews).mockResolvedValue({
    items: [
      {
        url: 'https://example.test/story',
        title: 'Studio ships patch',
        summary: 'A long summary that should truncate in the magazine densify row for readability.',
        source: 'Wire',
        published_at: '2026-07-29T08:00:00+00:00',
      },
    ],
  })

  const { container } = render(
    <ShellHarness>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )

  expect(await screen.findByText('Household note')).toBeInTheDocument()
  expect(container.querySelector('.od-news__hero')).toBeTruthy()
  expect(container.querySelector('.od-news__hero-title')).toHaveTextContent('Household note')
  expect(screen.getByText('Second note')).toBeInTheDocument()
  // UX-C14: headlines are image-forward cards now, not text-only rows.
  expect(container.querySelector('.od-news__cards')).toBeTruthy()
  expect(screen.getByText('Studio ships patch')).toBeInTheDocument()
  expect(screen.getByLabelText('News sections')).toBeInTheDocument()
})

test('headline cards show artwork when the feed supplies it', async () => {
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })
  // The first headline is promoted to the hero, so a card needs a second item.
  vi.mocked(gamingNewsApi.fetchGamingNews).mockResolvedValue({
    items: [
      { title: 'Hero story', url: 'https://example.com/hero', source: 'Example' },
      {
        title: 'Studio ships patch',
        url: 'https://example.com/a',
        source: 'Example',
        summary: 'Notes',
        image_url: 'https://cdn.example.com/art.jpg',
        published_at: '2026-08-12T12:00:00+00:00',
      },
    ],
  })
  const { container } = render(
    <ShellHarness>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )
  await screen.findByText('Studio ships patch')
  const wrap = container.querySelector('.od-news__card-art-wrap')
  expect(wrap).toBeTruthy()
  const art = wrap!.querySelector('img.od-news__card-art')
  expect(art).toBeTruthy()
  expect(art).toHaveAttribute('src', 'https://cdn.example.com/art.jpg')
  expect(wrap!.querySelector('.od-news__card-badge')).toHaveTextContent('Example')
  expect(wrap!.querySelector('time.od-news__card-when')).toBeTruthy()
  expect(container.querySelector('.od-news__card-body .od-news__meta')).toBeNull()
})

test('a feed with no artwork gets a placeholder, never a broken frame', async () => {
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })
  vi.mocked(gamingNewsApi.fetchGamingNews).mockResolvedValue({
    items: [
      { title: 'Hero story', url: 'https://example.com/hero', source: 'Example' },
      { title: 'No art here', url: 'https://example.com/b', source: 'Example' },
    ],
  })
  const { container } = render(
    <ShellHarness>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )
  await screen.findByText('No art here')
  expect(container.querySelector('.od-news__card-art--empty')).toBeTruthy()
  expect(container.querySelector('img.od-news__card-art')).toBeNull()
})

test('new chrome puts the sections in bar two with live counts', async () => {
  const user = userEvent.setup()
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({
    announcements: [
      { id: 1, title: 'Welcome', body: 'Hi', created_at: '2026-07-01T12:00:00+00:00' },
    ],
  })
  vi.mocked(gamingNewsApi.fetchGamingNews).mockResolvedValue({
    items: [{ title: 'Studio ships patch', url: 'https://example.com/a', source: 'Example' }],
  })

  render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )
  await screen.findByText('Welcome')

  // The h1 is gone; the sections it sat above are now the switcher.
  expect(screen.queryByRole('heading', { name: 'News' })).toBeNull()
  const headlines = screen.getByRole('button', { name: /Headlines/ })
  expect(headlines).toHaveTextContent('1')

  await user.click(headlines)
  expect(screen.getByText('Studio ships patch')).toBeInTheDocument()
  expect(screen.queryByText('Welcome')).toBeNull()
})

test('section counts stay hidden until the feeds have actually answered', async () => {
  // A "0" beside Free now would read as "there is nothing free" when the truth
  // is that the request has not come back.
  vi.mocked(announcementsApi.fetchAnnouncements).mockReturnValue(new Promise(() => {}))
  render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )

  expect(screen.getByRole('button', { name: /Free now/ }).textContent).not.toMatch(/\d/)
})

test('new chrome unfurls Card Grid RSS under the active layout name on the section bar', async () => {
  const user = userEvent.setup()
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })
  vi.mocked(gamingNewsApi.fetchGamingNews).mockResolvedValue({
    items: [{ title: 'Studio ships patch', url: 'https://example.com/a', source: 'Example' }],
  })

  render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <NewsPage />
    </ShellHarness>,
    { wrapper: MemoryRouter },
  )
  await screen.findByRole('heading', { name: 'Gaming headlines' })

  const trigger = screen.getByRole('button', { name: 'Card' })
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('button', { name: 'Grid' })).not.toBeInTheDocument()

  await user.click(trigger)
  expect(screen.getByRole('group', { name: 'View' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Grid' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'RSS' })).toBeInTheDocument()
})

test('RSS layout renders headline magazine rows instead of cards', async () => {
  const user = userEvent.setup()
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })
  vi.mocked(gamingNewsApi.fetchGamingNews).mockResolvedValue({
    items: [
      {
        title: 'Studio ships patch',
        url: 'https://example.com/a',
        source: 'Example',
        summary: 'Notes from the floor.',
      },
    ],
  })

  const { container } = render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <NewsPage />
    </ShellHarness>,
    {
      wrapper: MemoryRouter,
    },
  )
  await screen.findByText('Studio ships patch')
  await user.click(screen.getByRole('button', { name: /Headlines/ }))
  await user.click(screen.getByRole('button', { name: 'Card' }))
  await user.click(screen.getByRole('button', { name: 'RSS' }))

  expect(container.querySelector('.od-news__magazine')).toBeTruthy()
  expect(container.querySelector('.od-news__cards')).toBeNull()
  expect(window.localStorage.getItem('od.news.layout')).toBe('rss')
})

test('the Free now tab fills the stage rather than a half column', async () => {
  vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })
  vi.mocked(freeGamesApi.fetchFreeGames).mockResolvedValue({
    items: [
      {
        id: 9,
        store: 'steam',
        external_id: 'abc',
        title: 'Free Space Adventure',
        links: { https: 'https://example.test/claim' },
      },
    ],
  })

  const user = userEvent.setup()
  const { container } = render(
    <ShellHarness shell={{ enableNewChrome: true }}>
      <NewsPage />
    </ShellHarness>,
    {
      wrapper: MemoryRouter,
    },
  )
  await screen.findByText('Free Space Adventure')
  await user.click(screen.getByRole('button', { name: /Free now/ }))

  expect(container.querySelector('.od-news--fill')).toBeTruthy()
  expect(container.querySelector('.od-news--fill')?.getAttribute('data-tab')).toBe('free')
  expect(container.querySelector('.od-news__stage')).toBeTruthy()
  expect(container.querySelector('.od-news__headlines')).toBeNull()
})

describe('claim assist only opens http(s) and store launcher URLs', () => {
  async function claimWith(claim: LooseProps, itemHttps = 'https://example.test/claim') {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    vi.mocked(announcementsApi.fetchAnnouncements).mockResolvedValue({ announcements: [] })
    vi.mocked(freeGamesApi.fetchFreeGames).mockResolvedValue({
      items: [
        {
          id: 9,
          store: 'steam',
          external_id: 'abc',
          title: 'Free Space Adventure',
          links: { https: itemHttps },
          connected: true,
        },
      ],
    })
    vi.mocked(freeGamesApi.claimFreeGameAssist).mockResolvedValue({ ok: true, ...claim })

    const user = userEvent.setup()
    render(
      <ShellHarness>
        <NewsPage />
      </ShellHarness>,
      { wrapper: MemoryRouter },
    )
    await user.click(await screen.findByRole('button', { name: 'Free now' }))
    await user.click(await screen.findByRole('button', { name: /Claim & sync/ }))
    await waitFor(() => expect(freeGamesApi.claimFreeGameAssist).toHaveBeenCalledWith(9))
    return open
  }

  afterEach(() => {
    vi.restoreAllMocks()
  })

  test('opens the store deeplink the server built', async () => {
    const open = await claimWith({
      links: { protocol: 'steam://openurl/https://example.test/claim', https: null },
    })
    await waitFor(() =>
      expect(open).toHaveBeenCalledWith(
        'steam://openurl/https://example.test/claim',
        '_blank',
        'noopener,noreferrer',
      ),
    )
  })

  test('skips a javascript: claim URL and falls back to the next safe one', async () => {
    const open = await claimWith({
      links: { protocol: 'javascript:alert(document.domain)', https: 'https://example.test/ok' },
    })
    await waitFor(() =>
      expect(open).toHaveBeenCalledWith('https://example.test/ok', '_blank', 'noopener,noreferrer'),
    )
    expect(open).toHaveBeenCalledTimes(1)
  })

  test('opens nothing when every candidate is hostile', async () => {
    const open = await claimWith(
      { links: { protocol: 'data:text/html,<script>alert(1)</script>', https: 'javascript:1' } },
      'vbscript:msgbox(1)',
    )
    // The status line still appears, so the click was handled, just not opened.
    expect(await screen.findByText('Ownership updated.')).toBeInTheDocument()
    expect(open).not.toHaveBeenCalled()
  })
})
