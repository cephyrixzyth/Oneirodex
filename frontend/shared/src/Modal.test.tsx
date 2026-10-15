import { useRef, useState } from 'react'

import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { Modal } from './Modal'

test('renders nothing while closed and a dialog under body while open', () => {
  const { rerender, container } = render(
    <Modal open={false} label="Thing">
      <p>hi</p>
    </Modal>,
  )
  expect(screen.queryByRole('dialog')).toBeNull()
  rerender(
    <Modal open label="Thing" className="od-x" panelClassName="od-x__panel">
      <p>hi</p>
    </Modal>,
  )
  const dialog = screen.getByRole('dialog', { name: 'Thing' })
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(dialog).toHaveClass('od-x')
  expect(dialog.firstElementChild).toHaveClass('od-x__panel')
  // portal: the dialog is not inside the render container
  expect(container.contains(dialog)).toBe(false)
  expect(document.body.contains(dialog)).toBe(true)
})

test('aria-labelledby wins over label', () => {
  render(
    <Modal open labelledBy="t" label="ignored">
      <h2 id="t">Real title</h2>
    </Modal>,
  )
  expect(screen.getByRole('dialog', { name: 'Real title' })).toBeInTheDocument()
})

test('Escape closes; backdrop click closes; panel click does not', () => {
  const onClose = vi.fn()
  render(
    <Modal open onClose={onClose} label="T" className="ov" panelClassName="pn">
      <button type="button">inside</button>
    </Modal>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'inside' }))
  expect(onClose).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('dialog'))
  expect(onClose).toHaveBeenCalledTimes(1)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(2)
})

test('closeOnEscape=false keeps a busy dialog open', () => {
  const onClose = vi.fn()
  render(
    <Modal open onClose={onClose} closeOnEscape={false} label="T">
      <button type="button">x</button>
    </Modal>,
  )
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(onClose).not.toHaveBeenCalled()
})

test('focus moves to the first focusable on open, or to initialFocusRef', () => {
  function Host({ useRefTarget }: any) {
    const ref = useRef(null)
    return (
      <Modal open label="T" initialFocusRef={useRefTarget ? ref : undefined}>
        <button type="button">first</button>
        <button type="button" ref={ref}>
          second
        </button>
      </Modal>
    )
  }
  const { unmount } = render(<Host useRefTarget={false} />)
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'first' }))
  unmount()
  render(<Host useRefTarget />)
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'second' }))
})

test('Tab wraps inside the panel in both directions', () => {
  render(
    <Modal open label="T">
      <button type="button">a</button>
      <button type="button">b</button>
    </Modal>,
  )
  const a = screen.getByRole('button', { name: 'a' })
  const b = screen.getByRole('button', { name: 'b' })
  expect(document.activeElement).toBe(a)
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(b)
  fireEvent.keyDown(document, { key: 'Tab' })
  expect(document.activeElement).toBe(a)
})

test('focus returns to the opener on close', () => {
  function Host() {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          open
        </button>
        <Modal open={open} onClose={() => setOpen(false)} label="T">
          <button type="button" onClick={() => setOpen(false)}>
            close
          </button>
        </Modal>
      </>
    )
  }
  render(<Host />)
  const opener = screen.getByRole('button', { name: 'open' })
  opener.focus()
  fireEvent.click(opener)
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'close' }))
  fireEvent.click(screen.getByRole('button', { name: 'close' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(opener)
})

test('draft rerenders retain focus and Escape uses the latest callback and busy guard', () => {
  const firstClose = vi.fn()
  const latestClose = vi.fn()
  const fields = (
    <>
      <input aria-label="First field" />
      <input aria-label="Draft field" />
    </>
  )
  const { rerender } = render(
    <Modal open label="Draft" onClose={firstClose}>
      {fields}
    </Modal>,
  )
  const draft = screen.getByLabelText('Draft field')
  draft.focus()
  fireEvent.change(draft, { target: { value: 'retained' } })
  rerender(
    <Modal open label="Draft" onClose={latestClose} closeOnEscape={false}>
      {fields}
    </Modal>,
  )
  expect(draft).toHaveFocus()
  expect(draft).toHaveValue('retained')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(firstClose).not.toHaveBeenCalled()
  expect(latestClose).not.toHaveBeenCalled()
  rerender(
    <Modal open label="Draft" onClose={() => latestClose()}>
      {fields}
    </Modal>,
  )
  expect(draft).toHaveFocus()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(latestClose).toHaveBeenCalledTimes(1)
  expect(firstClose).not.toHaveBeenCalled()
})
