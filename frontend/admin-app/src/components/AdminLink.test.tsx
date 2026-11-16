import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, test } from 'vitest'
import { AdminLink, isAdminAppPath } from './AdminLink'

function CurrentRoute() {
  return <output data-testid="current-route">{useLocation().pathname}</output>
}

describe('AdminLink', () => {
  test('uses client-side navigation inside the admin router', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/settings']}>
        <AdminLink to="/admin/igdb_settings">IGDB settings</AdminLink>
        <CurrentRoute />
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('link', { name: 'IGDB settings' }))
    await waitFor(() =>
      expect(screen.getByTestId('current-route')).toHaveTextContent('/admin/igdb_settings'),
    )
  })

  test('renders as a usable anchor in isolated component renders without a router', () => {
    render(<AdminLink to="/admin/settings">Settings</AdminLink>)
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute(
      'href',
      '/admin/settings',
    )
  })

  test('keeps cross-app paths as native document links inside the admin router', () => {
    render(
      <MemoryRouter initialEntries={['/admin/help']}>
        <AdminLink to="/help">Member help</AdminLink>
        <CurrentRoute />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: 'Member help' })).toHaveAttribute('href', '/help')
    expect(screen.getByTestId('current-route')).toHaveTextContent('/admin/help')
  })

  test('only intercepts paths registered in the admin SPA', () => {
    expect(isAdminAppPath('/admin/newsletter/42?preview=1')).toBe(true)
    expect(isAdminAppPath('/admin/ops')).toBe(true)
    expect(isAdminAppPath('/admin/users')).toBe(true)
    expect(isAdminAppPath('/admin/library/edit/abc')).toBe(true)
    expect(isAdminAppPath('/scan_management?active_tab=manual')).toBe(true)
    expect(isAdminAppPath('/admin/legacy-jinja-page')).toBe(false)
    expect(isAdminAppPath('/library')).toBe(false)
    expect(isAdminAppPath('/help')).toBe(false)
  })
})
