import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchRelatedMedia } from '../api/gameDetails'
import { RelatedMediaStrip } from './RelatedMediaStrip'

vi.mock('../api/gameDetails', () => ({
  fetchRelatedMedia: vi.fn(),
}))

const items = [
  {
    id: 1,
    media_kind: 'film',
    title: 'The Movie',
    year: 2025,
    external_url: 'https://example.test/movie',
  },
]

describe('RelatedMediaStrip dialog focus', () => {
  beforeEach(() => {
    vi.mocked(fetchRelatedMedia).mockResolvedValue({
      items,
      kinds: [{ id: 'film', label: 'Film' }],
    } as any)
  })

  it('traps focus, closes with Escape, and restores focus to the launcher', async () => {
    const user = userEvent.setup()
    render(<RelatedMediaStrip gameUuid="game-1" />)

    const launcher = await screen.findByRole('button', { name: /The Movie/ })
    await user.click(launcher)

    const dialog = screen.getByRole('dialog', { name: 'The Movie' })
    const close = screen.getByRole('button', { name: 'Close' })
    const destination = screen.getByRole('link', { name: 'Where to find it' })
    expect(dialog).toBeInTheDocument()
    expect(close).toHaveFocus()

    await user.tab({ shift: true })
    expect(destination).toHaveFocus()
    await user.tab()
    expect(close).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(launcher).toHaveFocus()
  })
})
