import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { InvitesPage } from './InvitesPage'

vi.mock('@oneirodex/ui', () => ({
  InvitesPanel: () => <div>Invite management</div>,
}))

test('keeps the legacy account destinations on the full-page invite route', () => {
  render(
    <MemoryRouter initialEntries={['/user/invites']}>
      <InvitesPage />
    </MemoryRouter>,
  )

  expect(screen.getByRole('heading', { level: 2, name: 'Invites' })).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'Account settings' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Invites' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: 'Profile' })).toHaveAttribute(
    'href',
    '/settings_profile_view',
  )
  expect(screen.getByRole('link', { name: 'Password' })).toHaveAttribute(
    'href',
    '/settings_password',
  )
  expect(screen.getByRole('link', { name: 'Library' })).toHaveAttribute('href', '/library')
  expect(screen.getByText('Invite management')).toBeInTheDocument()
})
