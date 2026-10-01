import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ShellHarness } from '../testShell'
import { DiscoverSurprise } from './DiscoverSurprise'

function jsonResponse(body: unknown) {
  const payload = JSON.stringify(body)
  return {
    ok: true,
    headers: {
      get(name: string) {
        return String(name).toLowerCase() === 'content-type' ? 'application/json' : null
      },
    },
    json: async () => body,
    text: async () => payload,
  }
}

const GENRES = [
  { id: 7, name: 'Platformer' },
  { id: 9, name: 'Puzzle' },
]

function game(uuid: string, name: string) {
  return { uuid, name, cover_url: '', genres: [], is_favorite: false, has_local_override: false }
}

function mockSurprise(picks: Array<Record<string, unknown>>) {
  const calls: string[] = []
  let next = 0
  global.fetch = vi.fn((url) => {
    calls.push(String(url))
    const pick = picks[Math.min(next, picks.length - 1)]
    next += 1
    return Promise.resolve(jsonResponse({ ok: true, genres: GENRES, genre: null, ...pick }))
  }) as unknown as typeof global.fetch
  return calls
}

function renderSurprise() {
  return render(
    <MemoryRouter>
      <ShellHarness>
        <DiscoverSurprise />
      </ShellHarness>
    </MemoryRouter>,
  )
}

test('offers the member’s genres but draws nothing until asked', async () => {
  mockSurprise([{ game: game('g-1', 'Hidden Until Asked'), reason: 'Picked from what you play' }])
  renderSurprise()

  expect(await screen.findByRole('button', { name: 'Platformer' })).toBeInTheDocument()
  expect(screen.queryByText('Hidden Until Asked')).not.toBeInTheDocument()
})

test('a pick shows the title, and "another" asks not to repeat it', async () => {
  const calls = mockSurprise([
    { game: null, reason: '' },
    { game: game('g-1', 'First Pick'), reason: 'Picked from what you play' },
    { game: game('g-2', 'Second Pick'), reason: 'Picked from what you play' },
  ])
  const user = userEvent.setup()
  renderSurprise()

  await user.click(await screen.findByRole('button', { name: 'Pick something' }))
  expect((await screen.findAllByText('First Pick')).length).toBeGreaterThan(0)

  await user.click(screen.getByRole('button', { name: 'Another' }))
  expect((await screen.findAllByText('Second Pick')).length).toBeGreaterThan(0)
  expect(calls.at(-1)).toContain('exclude=g-1')
})

test('choosing a genre steers the draw and says so', async () => {
  const calls = mockSurprise([
    { game: null, reason: '' },
    { game: game('g-3', 'Genre Pick'), reason: 'From your Puzzle picks' },
  ])
  const user = userEvent.setup()
  renderSurprise()

  const chip = await screen.findByRole('button', { name: 'Puzzle' })
  await user.click(chip)

  expect((await screen.findAllByText('Genre Pick')).length).toBeGreaterThan(0)
  expect(chip).toHaveAttribute('aria-pressed', 'true')
  expect(calls.at(-1)).toContain('genre=9')
})

test('an empty draw is said plainly, not rendered as a broken tile', async () => {
  mockSurprise([
    { game: null, reason: '' },
    { game: null, reason: 'Nothing left you haven’t already tried.' },
  ])
  const user = userEvent.setup()
  renderSurprise()

  await user.click(await screen.findByRole('button', { name: 'Pick something' }))
  await waitFor(() =>
    expect(screen.getByText('Nothing left you haven’t already tried.')).toBeInTheDocument(),
  )
})
