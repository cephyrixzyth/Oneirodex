import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test } from 'vitest'
import { DashboardBoard } from './DashboardBoard'
import { defaultDashboardLayout } from './dashboardLayout'

const widgets = {
  status: <p>health</p>,
  'm-games': <p>games tile</p>,
  'm-cpu': <p>cpu tile</p>,
}

function board() {
  return render(
    <DashboardBoard
      widgets={widgets}
      widgetLabels={{ 'm-games': 'Games', 'm-cpu': 'CPU' }}
      defaultHidden={['m-cpu']}
      defaultLayout={() => defaultDashboardLayout().filter((item) => item.id in widgets)}
      storageKey="test-board-v1"
    />,
  )
}

describe('DashboardBoard controls', () => {
  beforeEach(() => window.localStorage.clear())

  test('optional widgets start hidden and Add widget brings them in', () => {
    board()
    expect(screen.queryByText('cpu tile')).not.toBeInTheDocument()
    const trigger = screen.getByRole('button', { name: /Add widget/ })
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-controls')
    fireEvent.click(screen.getByRole('button', { name: 'CPU' }))
    expect(screen.getByText('cpu tile')).toBeInTheDocument()
    expect(trigger).not.toHaveAttribute('aria-controls')
  })

  test('Add widget uses native Tab order and Escape restores focus', async () => {
    board()
    const user = userEvent.setup()
    const trigger = screen.getByRole('button', { name: /Add widget/ })
    expect(trigger).not.toHaveAttribute('aria-controls')
    fireEvent.click(trigger)
    expect(trigger.getAttribute('aria-controls')).toBe(
      screen.getByRole('group', { name: 'Widgets to add' }).id,
    )
    trigger.focus()
    await user.tab()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'CPU' }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('group', { name: 'Widgets to add' })).toBeNull()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(document.activeElement).toBe(trigger)
  })

  test('outside pointer dismissal keeps focus on its destination', () => {
    board()
    const trigger = screen.getByRole('button', { name: /Add widget/ })
    fireEvent.click(trigger)
    const outside = document.createElement('button')
    outside.className = 'test-outside-target'
    document.body.append(outside)
    outside.focus()
    fireEvent.pointerDown(outside)
    expect(screen.queryByRole('group', { name: 'Widgets to add' })).toBeNull()
    expect(document.activeElement).toBe(outside)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    outside.remove()
  })

  test('hide removes a widget and offers it back; hidden state persists', () => {
    board()
    fireEvent.click(screen.getByRole('button', { name: 'Hide Games' }))
    expect(screen.queryByText('games tile')).not.toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem('test-board-v1:hidden') || '[]')).toContain(
      'm-games',
    )
  })

  test('pinning locks the widget: no resize handles, size and hide disabled', () => {
    board()
    expect(screen.getByRole('button', { name: 'Resize Games' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pin Games' }))
    expect(screen.queryByRole('button', { name: 'Resize Games' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide Games' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Unpin Games' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  test('a size preset changes the widget width', () => {
    board()
    const item = document.querySelector('[data-widget="m-games"]') as HTMLElement
    fireEvent.click(screen.getByRole('button', { name: 'Games: Small width' }))
    expect(item.style.gridColumn).toContain('span 3')
  })

  test('arrow keys move a focused widget, shift+arrows resize it', () => {
    board()
    const item = document.querySelector('[data-widget="m-games"]') as HTMLElement
    const before = item.style.gridColumn
    fireEvent.keyDown(item, { key: 'ArrowRight', shiftKey: true })
    expect(item.style.gridColumn).not.toBe(before)
  })
})
