import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { NewsCard } from './NewsCard'

function renderCard(item: Record<string, unknown>) {
  return render(
    <MemoryRouter>
      <NewsCard item={item} />
    </MemoryRouter>,
  )
}

test('a free game shows when the giveaway ends, not when it was last seen', () => {
  renderCard({
    kind: 'free_game',
    id: 'free-1',
    title: 'Lantern Keep',
    store: 'epic',
    href: '/news#free-games',
    published_at: '2026-11-20T10:00:00Z',
    ends_at: '2026-12-03T16:00:00Z',
  })
  expect(screen.getByText(/^Until /)).toBeInTheDocument()
  expect(screen.getByText('Epic')).toBeInTheDocument()
})

test('a free game with no end date falls back to its published date', () => {
  renderCard({
    kind: 'free_game',
    id: 'free-2',
    title: 'Fable of Wires',
    store: 'gog',
    published_at: '2026-11-20T10:00:00Z',
  })
  expect(screen.queryByText(/^Until /)).not.toBeInTheDocument()
})
