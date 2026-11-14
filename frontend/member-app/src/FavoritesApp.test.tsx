import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FavoritesApp } from './FavoritesApp'

function jsonResponse(body: any) {
  const payload = JSON.stringify(body)
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(payload),
  }
}

afterEach(() => {
  window.localStorage.removeItem('od.library.layout')
})

test('fetches favorite games and renders them with the shared grid', async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    jsonResponse({
      games: [
        {
          uuid: 'favorite-1',
          name: 'Favorite VR Game',
          cover_url: '/static/library/images/favorite.jpg',
          is_favorite: true,
          has_local_override: true,
          is_vr: true,
          genres: ['Adventure'],
          user_status: 'beaten',
        },
      ],
      total: 1,
      pages: 1,
      current_page: 1,
    }),
  )
  vi.stubGlobal('fetch', fetchMock)

  render(<FavoritesApp initialConfig={{ showPlayStatus: true, isAdmin: false, perPage: 20 }} />)

  expect(screen.getByText(/Loading favorites/)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText('Favorite VR Game')).toBeInTheDocument())
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/favorites?page=1&per_page=20',
    expect.objectContaining({ credentials: 'include' }),
  )
  expect(document.querySelectorAll('[data-library-grid], [data-library-shelves]')).toHaveLength(1)
  expect(screen.getByRole('img', { name: 'Favorite VR Game' })).toHaveAttribute(
    'src',
    '/static/library/images/favorite.jpg',
  )
  expect(screen.getByTitle('Uses local metadata or images')).toBeInTheDocument()
  expect(screen.getByTitle('Virtual Reality')).toBeInTheDocument()
  expect(screen.getByLabelText('Game status: Beaten')).toBeInTheDocument()
})

test('shows an empty message when there are no favorites', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(jsonResponse({ games: [], total: 0, pages: 1, current_page: 1 })),
  )

  render(<FavoritesApp initialConfig={{ showPlayStatus: false, isAdmin: false }} />)

  expect(await screen.findByText("You haven't added any favorites yet!")).toBeInTheDocument()
})

test('removes a card after it is unfavorited', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          games: [
            {
              uuid: 'favorite-1',
              name: 'Favorite Game',
              cover_url: '/static/favorite.jpg',
              is_favorite: true,
              has_local_override: false,
              is_vr: false,
              genres: [],
              user_status: null,
            },
          ],
          total: 1,
          pages: 1,
          current_page: 1,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ is_favorite: false })),
  )
  render(<FavoritesApp initialConfig={{ showPlayStatus: false, isAdmin: false }} />)
  await screen.findByText('Favorite Game')

  await user.click(
    screen.getByRole('button', {
      name: 'Remove Favorite Game from favorites',
    }),
  )
  expect(await screen.findByText("You haven't added any favorites yet!")).toBeInTheDocument()
})

test('returns to the previous page when the last favorite on a later page is removed', async () => {
  const user = userEvent.setup()
  const favorite = (uuid: string, name: string) => ({
    uuid,
    name,
    cover_url: '/static/favorite.jpg',
    is_favorite: true,
    has_local_override: false,
    is_vr: false,
    genres: [],
    user_status: null,
  })
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      jsonResponse({
        games: [favorite('page-one', 'Favorite on page one')],
        total: 21,
        pages: 2,
        current_page: 1,
      }),
    )
    .mockResolvedValueOnce(
      jsonResponse({
        games: [favorite('page-two', 'Last favorite on page two')],
        total: 21,
        pages: 2,
        current_page: 2,
      }),
    )
    .mockResolvedValueOnce(jsonResponse({ is_favorite: false }))
    .mockResolvedValueOnce(
      jsonResponse({
        games: [favorite('page-one', 'Favorite on page one')],
        total: 20,
        pages: 1,
        current_page: 1,
      }),
    )
  vi.stubGlobal('fetch', fetchMock)

  render(<FavoritesApp initialConfig={{ showPlayStatus: false, isAdmin: false, perPage: 20 }} />)
  await screen.findByText('Favorite on page one')
  await user.click(screen.getByRole('button', { name: 'Next' }))
  await screen.findByText('Last favorite on page two')
  await user.click(
    screen.getByRole('button', { name: 'Remove Last favorite on page two from favorites' }),
  )
  expect(await screen.findByText('Favorite on page one')).toBeInTheDocument()
  expect(screen.getByText('Page 1 of 1')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/api/favorites?page=1&per_page=20', expect.anything())
})
