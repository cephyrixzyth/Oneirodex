import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, test } from 'vitest'
import AdminCommandPalette from './AdminCommandPalette'

function CurrentRoute() {
  return <output data-testid="current-route">{useLocation().pathname}</output>
}

describe('AdminCommandPalette', () => {
  test('Enter navigates within the admin app without a document reload', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/dashboard']}>
        <AdminCommandPalette />
        <CurrentRoute />
      </MemoryRouter>,
    )

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    const search = screen.getByRole('textbox', { name: 'Search admin' })
    fireEvent.change(search, { target: { value: 'smtp' } })
    fireEvent.keyDown(search, { key: 'Enter' })

    await waitFor(() =>
      expect(screen.getByTestId('current-route')).toHaveTextContent('/admin/smtp_settings'),
    )
    expect(screen.queryByRole('dialog', { name: 'Search admin' })).toBeNull()
  })

  test('click navigates within the admin app and closes the palette', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/dashboard']}>
        <AdminCommandPalette />
        <CurrentRoute />
      </MemoryRouter>,
    )

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    const search = screen.getByRole('textbox', { name: 'Search admin' })
    fireEvent.change(search, { target: { value: 'smtp' } })
    fireEvent.click(screen.getAllByRole('option')[0])

    await waitFor(() =>
      expect(screen.getByTestId('current-route')).toHaveTextContent('/admin/smtp_settings'),
    )
    expect(screen.queryByRole('dialog', { name: 'Search admin' })).toBeNull()
  })
})
