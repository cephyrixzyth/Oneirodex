import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { arrangeDiscoverSections, DiscoverApp } from './DiscoverApp'
import { ShellHarness } from './testShell'

/** Shelves link out, so the tree needs a router even when nothing links yet. */
function renderDiscover(props = {}) {
  return render(
    <MemoryRouter>
      <ShellHarness {...props}>
        <DiscoverApp />
      </ShellHarness>
    </MemoryRouter>,
  )
}

function jsonResponse(body: any) {
  const payload = JSON.stringify(body)
  return {
    ok: true,
    headers: {
      get(name: any) {
        return String(name).toLowerCase() === 'content-type' ? 'application/json' : null
      },
    },
    json: async () => body,
    text: async () => payload,
  }
}

function mockDiscoverFetch(
  sections: any,
  { pins = [], maxPins = 3 }: { pins?: string[]; maxPins?: number } = {},
) {
  global.fetch = vi.fn((url) =>
    Promise.resolve(
      String(url).includes('/pins')
        ? jsonResponse({ ok: true, pins, max_pins: maxPins, available: [] })
        : jsonResponse({ sections }),
    ),
  ) as unknown as typeof global.fetch
}

test('renders discover section titles and games as horizontal shelves', async () => {
  mockDiscoverFetch([
    {
      identifier: 'latest_games',
      title: 'Latest Games',
      games: [
        {
          uuid: 'discover-1',
          name: 'Discover VR Game',
          cover_url: '/static/library/images/discover.jpg',
          is_favorite: false,
          has_local_override: true,
          is_vr: true,
          genres: ['Adventure'],
        },
      ],
    },
    {
      identifier: 'highest_rated',
      title: 'Highest Rated',
      games: [
        {
          uuid: 'discover-2',
          name: 'Top Game',
          cover_url: '/static/newstyle/default_cover.jpg',
          is_favorite: true,
          has_local_override: false,
          is_vr: false,
          genres: [],
        },
      ],
    },
  ])

  renderDiscover()

  expect(await screen.findByRole('heading', { name: 'Latest Games' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Highest Rated' })).toBeInTheDocument()
  expect(document.querySelectorAll('.od-shelf__track')).toHaveLength(2)
  expect(screen.getByRole('img', { name: 'Discover VR Game' })).toHaveAttribute(
    'src',
    '/static/library/images/discover.jpg',
  )
  expect(screen.getByTitle('Uses local metadata or images')).toBeInTheDocument()
  expect(screen.getByTitle('Virtual Reality')).toBeInTheDocument()
  expect(global.fetch).toHaveBeenCalledWith(
    '/api/discover/sections',
    expect.objectContaining({ credentials: 'include' }),
  )
})

test('does not render empty discover sections', async () => {
  mockDiscoverFetch([
    {
      identifier: 'most_favorited',
      title: 'Most Favorited Games',
      games: [],
    },
  ])

  renderDiscover()

  await waitFor(() => {
    expect(screen.getByText(/No Discover shelves/i)).toBeInTheDocument()
  })
  expect(screen.queryByRole('heading', { name: 'Most Favorited Games' })).not.toBeInTheDocument()
  expect(document.querySelector('.od-shelf__track')).not.toBeInTheDocument()
})

test('a row deeper than it can show offers a way to see all of it', async () => {
  mockDiscoverFetch([
    {
      identifier: 'latest_games',
      title: 'Latest Games',
      total_count: 1,
      has_more: true,
      more_href: '/discover/latest_games',
      games: [{ uuid: 'd-1', name: 'Deep Row Game', cover_url: '/c.jpg', genres: [] }],
    },
  ])

  renderDiscover()

  const seeAll = await screen.findByRole('link', { name: 'See all in Latest Games' })
  expect(seeAll).toHaveAttribute('href', '/discover/latest_games')
})

test('a row that shows everything it has does not claim there is more', async () => {
  mockDiscoverFetch([
    {
      identifier: 'latest_games',
      title: 'Latest Games',
      total_count: 1,
      has_more: false,
      more_href: '/discover/latest_games',
      games: [{ uuid: 'd-1', name: 'Shallow Row Game', cover_url: '/c.jpg', genres: [] }],
    },
  ])

  renderDiscover()

  expect(await screen.findByRole('heading', { name: 'Latest Games' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /See all/ })).not.toBeInTheDocument()
})

test('shows Loading Discover while sections fetch', async () => {
  let resolveFetch: ((value: unknown) => void) | undefined
  // Keyed by URL: the page also asks for the member's pins, and a single
  // shared resolver would be reassigned by whichever request went out last.
  global.fetch = vi.fn((url) => {
    if (String(url).includes('/pins')) {
      return Promise.resolve(jsonResponse({ ok: true, pins: [], max_pins: 3, available: [] }))
    }
    return new Promise((resolve) => {
      resolveFetch = resolve
    })
  }) as unknown as typeof global.fetch

  renderDiscover()
  expect(screen.getByText('Loading Discover')).toBeInTheDocument()

  resolveFetch!(jsonResponse({ sections: [] }))

  await waitFor(() => {
    expect(screen.getByText(/No Discover shelves/i)).toBeInTheDocument()
  })
})

test('a news row renders article tiles, not game tiles', async () => {
  mockDiscoverFetch([
    {
      identifier: 'news',
      title: 'News',
      item_kind: 'articles',
      reason: 'From the server and the stores',
      total_count: 2,
      has_more: false,
      items: [
        {
          kind: 'announcement',
          id: 'announcement-1',
          title: 'Server maintenance Sunday',
          summary: 'Back by evening.',
          href: '/news',
          published_at: '2026-08-19T10:00:00Z',
        },
        {
          kind: 'free_game',
          id: 'free-2',
          title: 'Free This Week',
          summary: 'Claim before Thursday.',
          store: 'epic',
          href: '/news#free-games',
          published_at: '2026-08-18T10:00:00Z',
        },
      ],
    },
  ])

  renderDiscover()

  expect(await screen.findByRole('heading', { name: 'News' })).toBeInTheDocument()
  // The row says why it is there — the provenance rule.
  expect(screen.getByText('From the server and the stores')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Server maintenance Sunday/ })).toHaveAttribute(
    'href',
    '/news',
  )
  expect(screen.getByText('Epic')).toBeInTheDocument()
})

test('an article row is not dropped for having no games key', async () => {
  // The feed filter used to read `section.games` only, which hid article rows
  // entirely because they never carry that key.
  mockDiscoverFetch([
    {
      identifier: 'news',
      title: 'News',
      item_kind: 'articles',
      total_count: 1,
      items: [{ kind: 'announcement', id: 'a-1', title: 'Still here', href: '/news' }],
    },
  ])

  renderDiscover()

  expect(await screen.findByRole('heading', { name: 'News' })).toBeInTheDocument()
  expect(screen.queryByText(/No Discover shelves/i)).not.toBeInTheDocument()
})

test('a member can pin a row to the top of their feed', async () => {
  mockDiscoverFetch(
    [
      {
        identifier: 'latest_games',
        title: 'Latest Games',
        total_count: 1,
        games: [{ uuid: 'p-1', name: 'Pinnable', cover_url: '/c.jpg', genres: [] }],
      },
    ],
    { pins: [], maxPins: 3 },
  )

  renderDiscover()

  const pin = await screen.findByRole('button', { name: 'Pin' })
  expect(pin).toHaveAttribute('aria-pressed', 'false')
})

test('the pin control is disabled once the member has used every pin', async () => {
  // A control that silently did nothing would read as a broken button.
  mockDiscoverFetch(
    [
      {
        identifier: 'latest_games',
        title: 'Latest Games',
        total_count: 1,
        games: [{ uuid: 'p-1', name: 'Pinnable', cover_url: '/c.jpg', genres: [] }],
      },
    ],
    { pins: ['a', 'b', 'c'], maxPins: 3 },
  )

  renderDiscover()

  const pin = await screen.findByRole('button', { name: 'Pin' })
  expect(pin).toBeDisabled()
})

test('hiding a row takes it off the feed immediately', async () => {
  const user = userEvent.setup()
  mockDiscoverFetch([
    {
      identifier: 'latest_games',
      title: 'Latest Games',
      total_count: 1,
      games: [{ uuid: 'a-1', name: 'Alpha', cover_url: '/c.jpg', genres: [] }],
    },
    {
      identifier: 'highest_rated',
      title: 'Highest Rated',
      total_count: 1,
      games: [{ uuid: 'b-1', name: 'Beta', cover_url: '/c.jpg', genres: [] }],
    },
  ])

  renderDiscover()
  expect(await screen.findByRole('heading', { name: 'Latest Games' })).toBeInTheDocument()

  await user.click(screen.getAllByRole('button', { name: 'Hide' })[0])

  await waitFor(() => {
    expect(screen.queryByRole('heading', { name: 'Latest Games' })).not.toBeInTheDocument()
  })
  expect(screen.getByRole('heading', { name: 'Highest Rated' })).toBeInTheDocument()
})

test('pinning a row moves it to the top of the feed immediately', async () => {
  const user = userEvent.setup()
  mockDiscoverFetch([
    {
      identifier: 'latest_games',
      title: 'Latest Games',
      total_count: 1,
      games: [{ uuid: 'a-1', name: 'Alpha', cover_url: '/c.jpg', genres: [] }],
    },
    {
      identifier: 'highest_rated',
      title: 'Highest Rated',
      total_count: 1,
      games: [{ uuid: 'b-1', name: 'Beta', cover_url: '/c.jpg', genres: [] }],
    },
  ])

  renderDiscover()
  await screen.findByRole('heading', { name: 'Latest Games' })

  await user.click(screen.getAllByRole('button', { name: 'Pin' })[1])

  await waitFor(() => {
    // Shelf headings only: the Surprise me panel above the feed is not a row
    // and does not take part in pin order.
    const headings = screen
      .getAllByRole('heading', { level: 2 })
      .map((node) => node.textContent)
      .filter((text) => text !== 'Surprise me')
    expect(headings[0]).toContain('Highest Rated')
  })
})

test('a news row always offers See all to the News page', async () => {
  mockDiscoverFetch([
    {
      identifier: 'news',
      title: 'News',
      item_kind: 'articles',
      total_count: 1,
      has_more: false,
      items: [{ kind: 'announcement', id: 'a-1', title: 'Still here', href: '/news' }],
    },
  ])

  renderDiscover()

  expect(await screen.findByRole('link', { name: /^See all$/ })).toHaveAttribute('href', '/news')
  expect(screen.getByRole('link', { name: 'See all in News' })).toHaveAttribute('href', '/news')
})

test('arrangeDiscoverSections hides and pins without waiting for a refetch', () => {
  const sections = [
    { identifier: 'a', title: 'A', games: [{ uuid: '1' }] },
    { identifier: 'b', title: 'B', games: [{ uuid: '2' }] },
    { identifier: 'c', title: 'C', games: [{ uuid: '3' }] },
  ]
  const arranged = arrangeDiscoverSections(sections, { pins: ['c', 'a'], hidden: ['b'] })
  expect(arranged.map((row: any) => row.identifier)).toEqual(['c', 'a'])
})
