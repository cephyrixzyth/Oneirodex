import { render, screen } from '@testing-library/react'
import { AnticheatFact } from './AnticheatFact'

describe('AnticheatFact (INSP-35)', () => {
  it('reads the community status as reports, with the anti-cheat names and a source link', () => {
    render(
      <AnticheatFact
        report={{
          status: 'denied',
          anticheats: ['Easy Anti-Cheat'],
          reports: 2,
          source_url: 'https://example.invalid/game/rocket',
        }}
      />,
    )
    const chip = screen.getByText('Denied')
    expect(chip.getAttribute('data-status')).toBe('denied')
    expect(screen.getByText('Easy Anti-Cheat')).toBeTruthy()
    const link = screen.getByRole('link', { name: 'community reports, 2 updates' })
    expect(link.getAttribute('href')).toBe('https://example.invalid/game/rocket')
    expect(link.getAttribute('rel')).toContain('noopener')
  })

  it('falls back to Unknown wording and plain text without a source', () => {
    render(<AnticheatFact report={{ status: 'weird', anticheats: [], reports: 0 }} />)
    expect(screen.getByText('Unknown').getAttribute('data-status')).toBe('weird')
    expect(screen.getByText('community reports')).toBeTruthy()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('does not turn a non-http source into a clickable link', () => {
    render(
      <AnticheatFact
        report={{
          status: 'unknown',
          anticheats: [],
          reports: 1,
          source_url: 'javascript:alert(1)',
        }}
      />,
    )
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('community reports, 1 update')).toBeTruthy()
  })
})
