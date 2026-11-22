import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { MoonfallPanel } from './MoonfallPanel'
import { newMoonfall } from './model'
import type { MoonfallSession } from './session'
const view: ReturnType<MoonfallSession['view']> = {
  hasSaved: true,
  confirm: null,
  status: 'ready',
  message: 'Saved run available.',
  serverChoice: false,
  busy: false,
  chosen: false,
  practice: false,
  menuPage: 'main',
  state: newMoonfall(),
  runtimeStatus: 'idle',
  updatedAt: null,
}
function setup(value = view) {
  const command = vi.fn()
  const input = vi.fn()
  const settings = vi.fn()
  render(<MoonfallPanel view={value} command={command} input={input} settings={settings} />)
  return { command, input, settings }
}
test('offers explicit resume and new run without starting automatically', () => {
  const { command } = setup()
  expect(command).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Resume saved run' }))
  expect(command).toHaveBeenCalledWith('resume')
  fireEvent.click(screen.getByRole('button', { name: 'New run' }))
  expect(command).toHaveBeenCalledWith('new')
})
test('presents conflict choices and releases held controls on cancellation', () => {
  const { command, input } = setup({ ...view, serverChoice: true })
  fireEvent.click(screen.getByRole('button', { name: 'Load server run' }))
  expect(command).toHaveBeenCalledWith('load-server')
  const left = screen.getByRole('button', { name: 'Left flipper' })
  fireEvent.pointerDown(left, { pointerId: 1 })
  fireEvent.pointerCancel(left, { pointerId: 1 })
  expect(input).toHaveBeenCalledWith('left', true, 'panel-left')
  expect(input).toHaveBeenCalledWith('left', false, 'panel-left')
})
test('exposes mute and motion settings without inline style literals', () => {
  const { settings } = setup()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Reduced motion' }))
  expect(settings).toHaveBeenCalledWith({ reducedMotion: true })
  fireEvent.click(screen.getByRole('checkbox', { name: 'Mute sound' }))
  expect(settings).toHaveBeenCalledWith({ muted: false })
})

test('names a finished run and shows its final score', () => {
  setup({ ...view, runtimeStatus: 'result', chosen: true })
  expect(screen.getByRole('heading', { name: 'Run finished' })).toBeInTheDocument()
})
