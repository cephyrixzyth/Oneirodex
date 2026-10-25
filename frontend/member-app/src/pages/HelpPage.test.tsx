import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { expect, test } from 'vitest'
import { HelpPage } from './HelpPage'
import { ShellHarness } from '../testShell'

test('opens on Getting started rather than on a wall of closed topics', () => {
  render(
    <MemoryRouter>
      <ShellHarness>
        <HelpPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  expect(screen.getByRole('heading', { name: 'Help' })).toBeInTheDocument()
  // The card is the control; the answer is already underneath it.
  expect(screen.getByRole('button', { name: /Getting started/i })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(screen.getByText(/Ctrl\+K \/ ⌘K/)).toBeInTheDocument()
  // A topic nobody picked contributes its card, not its bullets.
  expect(screen.queryByText(/oh-NY-roh-dex/)).toBeNull()
  // Report is a rail destination, not a Help control.
  expect(screen.queryByRole('link', { name: /Report/i })).toBeNull()
})

test('picking a card swaps the pane underneath', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <ShellHarness shell={{ enableNewChrome: true }}>
        <HelpPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  await user.click(screen.getByRole('button', { name: /Browser play & BIOS/i }))
  expect(screen.getByText(/PS5 and Xbox Series stay catalog-only/)).toBeInTheDocument()
  // One pane at a time: the topic it replaced is back to being a card only.
  expect(screen.queryByText(/Ctrl\+K \/ ⌘K/)).toBeNull()
})

test('Big Picture help lists the supported controls and child download restriction', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <ShellHarness>
        <HelpPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  await user.click(screen.getByRole('button', { name: /Controllers & VR/i }))

  expect(
    screen.getByText(/Enter \/ A opens; D \/ X downloads; B opens Attract; Y toggles Friends/i),
  ).toBeInTheDocument()
  expect(screen.getByText(/Child downloads are unavailable/i)).toBeInTheDocument()
})

test('one fold button, and its label names the state it moves you to', async () => {
  // Expand all and Collapse all as a permanent pair meant one of the two was
  // always a no-op. It is one control that reports which mode you are in.
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <ShellHarness shell={{ enableNewChrome: true }}>
        <HelpPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  const fold = screen.getByRole('button', { name: 'Expand all' })
  expect(fold.closest('.od-seg')?.getAttribute('aria-label')).toBe('Help')
  expect(screen.queryByRole('button', { name: 'Collapse all' })).toBeNull()

  await user.click(fold)
  expect(screen.getByRole('button', { name: 'Collapse all' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Expand all' })).toBeNull()
  // Straight-through reading: every topic's body is on the page at once.
  expect(screen.getByText(/oh-NY-roh-dex/)).toBeInTheDocument()
  expect(screen.getByText(/Genesis family \(including SG-1000\)/)).toBeInTheDocument()
  expect(screen.getByText(/one tile per title/i)).toBeInTheDocument()
  expect(screen.getByText(/Set completeness/)).toBeInTheDocument()
  expect(screen.getByText(/Licensed catalog/)).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Collapse all' }))
  expect(screen.getByText(/Ctrl\+K \/ ⌘K/)).toBeInTheDocument()
  expect(screen.queryByText(/oh-NY-roh-dex/)).toBeNull()
})

test('the bar carries the fold control and nothing else', () => {
  // The five group chips jumped into a stack of accordions that no longer
  // exists — the card grid is the index now. "N of 13 open" went with them:
  // with one pane open the number is always 1, and it was never actionable.
  render(
    <MemoryRouter>
      <ShellHarness shell={{ enableNewChrome: true }}>
        <HelpPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  expect(screen.queryByRole('heading', { name: 'Help' })).toBeNull()
  expect(screen.getByRole('heading', { name: 'How Oneirodex works' })).toBeInTheDocument()
  for (const group of ['Start', 'Collection', 'Playing', 'Community', 'Support']) {
    expect(screen.queryByRole('button', { name: group })).toBeNull()
  }
  expect(screen.queryByText(/of 13 open/)).toBeNull()
})

test('every topic card carries a theme tone and a glyph', () => {
  // Thirteen identical grey cards are found by re-reading every heading. The
  // tone must come from the token set, not from a hex picked in the page.
  const { container } = render(
    <MemoryRouter>
      <ShellHarness shell={{ enableNewChrome: true }}>
        <HelpPage />
      </ShellHarness>
    </MemoryRouter>,
  )

  const cards = container.querySelectorAll('.od-help__card')
  expect(cards.length).toBeGreaterThan(0)
  const allowed = new Set(['accent', 'info', 'success', 'warning', 'danger'])
  for (const card of cards) {
    expect(allowed.has(card.getAttribute('data-tone')!)).toBe(true)
    expect(card.querySelector('.od-help__card-mark svg')).not.toBeNull()
  }
})
