import { fireEvent, render, screen } from '@testing-library/react'
import { App } from './App'

describe('UI catalog', () => {
  it('renders shared exports, real icon entries, and the shared filter specimen', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'UI catalog' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Rail icons' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Theme pack drawings' })).toBeInTheDocument()
    expect(
      screen.getByText(
        /other packs draw their 17 declared icons; every other shared glyph keeps its standard outline shape/i,
      ),
    ).toBeInTheDocument()
    expect(screen.getAllByText('17 shown · 17 declared')).toHaveLength(6)
    expect(screen.getAllByText('Shared drawing · all eras').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('discover era variants')).toBeInTheDocument()
    expect(screen.getAllByText('Pixel').length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: 'Applied filter example' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Filter shared exports' })).toBeInTheDocument()
    expect(screen.getByText('6 matching shared exports')).toHaveAttribute('role', 'status')
    expect(screen.getByRole('button', { name: 'Open modal preview' })).toHaveClass('od-btn')
  })

  it('renders installed theme-pack SVGs as inspectable accent masks', () => {
    const { container } = render(<App />)
    expect(container.querySelectorAll('.catalog__pack-glyph')).toHaveLength(85)
    expect(container.querySelectorAll('.catalog__pack-glyph-missing')).toHaveLength(0)
    expect(screen.getByText('Outline')).toBeInTheDocument()
    expect(container.querySelector('.catalog__pack')?.getAttribute('open')).not.toBeNull()
    fireEvent.change(screen.getByRole('searchbox', { name: 'Find an icon' }), {
      target: { value: 'plug' },
    })
    expect(
      [...container.querySelectorAll('.catalog__icon > code')].map((node) => node.textContent),
    ).toEqual(['integrations', 'plugins'])
    expect(screen.getByText('Aliases: plug')).toBeInTheDocument()
  })

  it('filters the shared export table and clears back to the applied all-results state', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Navigation' }))
    expect(screen.getByRole('button', { name: 'Navigation' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByText('1 matching shared exports')).toHaveAttribute('role', 'status')
    expect(screen.getByText('RailIcon')).toBeInTheDocument()
    expect(screen.queryByText('Button')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getByText('6 matching shared exports')).toHaveAttribute('role', 'status')
    expect(screen.getByText('Button')).toBeInTheDocument()
  })

  it('offers a scoped light preview while keeping the dark palette as the initial theme', () => {
    render(<App />)
    const palette = screen.getByRole('main')
    expect(palette).toHaveClass('catalog--dark')
    fireEvent.click(screen.getByRole('button', { name: 'Light' }))
    expect(palette).toHaveClass('catalog--light')
    expect(palette.style.colorScheme).toBe('light')
    expect(palette.style.getPropertyValue('--od-accent')).toMatch(/^rgb\(/)
    expect(palette.style.getPropertyValue('--od-focus-ring')).toMatch(/^rgb\(/)
  })
})
