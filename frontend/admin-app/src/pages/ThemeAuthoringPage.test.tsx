import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ThemeAuthoringPage } from './ThemeAuthoringPage'

describe('ThemeAuthoringPage', () => {
  it('preserves the authoring guide and links back to theme management', () => {
    render(
      <MemoryRouter>
        <ThemeAuthoringPage />
      </MemoryRouter>,
    )
    expect(
      screen.getByRole('heading', { name: 'Creating Your Own Theme', level: 1 }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Correct ZIP structure' })).toBeInTheDocument()
    expect(
      screen.getByText(
        'Package a ZIP with theme.json and CSS at the archive root, then upload it from Manage Themes.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(/extra folder layer; upload will fail/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Themes' })).toHaveAttribute(
      'href',
      '/admin/themes',
    )
  })
})
