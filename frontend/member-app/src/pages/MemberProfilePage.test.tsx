import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Link, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchMemberProfile } from '../api/social'
import { MemberProfilePage } from './MemberProfilePage'

vi.mock('../api/social', () => ({
  fetchMemberProfile: vi.fn(),
}))

function renderProfiles() {
  return render(
    <MemoryRouter initialEntries={['/members/a']}>
      <nav>
        <Link to="/members/a">Profile A</Link>
        <Link to="/members/b">Profile B</Link>
      </nav>
      <Routes>
        <Route path="/members/:userId" element={<MemberProfilePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('MemberProfilePage identity transitions', () => {
  beforeEach(() => vi.mocked(fetchMemberProfile).mockReset())

  it('clears a prior profile error when navigating to a valid profile', async () => {
    vi.mocked(fetchMemberProfile)
      .mockRejectedValueOnce(new Error('Profile unavailable'))
      .mockResolvedValueOnce({ user: { name: 'Member B' }, recent_games: [] } as any)
    const user = userEvent.setup()
    renderProfiles()

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load profile.')
    await user.click(screen.getByRole('link', { name: 'Profile B' }))

    expect(await screen.findByRole('heading', { name: 'Member B' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('retries a failed profile request without requiring navigation', async () => {
    vi.mocked(fetchMemberProfile)
      .mockRejectedValueOnce(new Error('Temporary outage'))
      .mockResolvedValueOnce({ user: { name: 'Member A' }, recent_games: [] } as any)
    const user = userEvent.setup()
    renderProfiles()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Member A' })).toBeInTheDocument()
  })

  it('does not show the previous identity while the next profile is loading', async () => {
    let resolveB!: (value: any) => void
    vi.mocked(fetchMemberProfile)
      .mockResolvedValueOnce({ user: { name: 'Member A' }, recent_games: [] } as any)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveB = resolve
          }) as any,
      )
    const user = userEvent.setup()
    renderProfiles()
    expect(await screen.findByRole('heading', { name: 'Member A' })).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Profile B' }))
    expect(screen.queryByRole('heading', { name: 'Member A' })).not.toBeInTheDocument()
    expect(await screen.findByRole('status')).toHaveTextContent('Loading profile')

    resolveB({ user: { name: 'Member B' }, recent_games: [] })
    expect(await screen.findByRole('heading', { name: 'Member B' })).toBeInTheDocument()
  })
})
