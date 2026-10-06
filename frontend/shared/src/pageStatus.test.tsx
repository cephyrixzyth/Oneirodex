import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { PageStatus, resolveErrorDetail, resolveErrorMessage } from './pageStatus'

test('resolveErrorMessage accepts every shape still in the tree', () => {
  // The backend is mid-migration onto the GT-B1 envelope, so all of these
  // still reach the UI and each one has to yield the human sentence.
  expect(resolveErrorMessage('plain string')).toBe('plain string')
  expect(resolveErrorMessage({ error: 'envelope sentence' })).toBe('envelope sentence')
  expect(resolveErrorMessage({ message: 'legacy sentence' })).toBe('legacy sentence')
  expect(resolveErrorMessage({ error: { message: 'nested' } })).toBe('nested')
  expect(resolveErrorMessage(new Error('thrown'))).toBe('thrown')
})

test('resolveErrorMessage falls back rather than showing nothing', () => {
  expect(resolveErrorMessage(null)).toBe('Something went wrong.')
  expect(resolveErrorMessage({})).toBe('Something went wrong.')
  expect(resolveErrorMessage('   ')).toBe('Something went wrong.')
  expect(resolveErrorMessage(null, 'custom')).toBe('custom')
})

test('the detail line carries status and error_code, never the headline', () => {
  const err = Object.assign(new Error('Boom'), { status: 503, error_code: 'unavailable' })
  // An Error still has to yield these — adminError throws one carrying both,
  // so bailing on `instanceof Error` would drop the fields entirely.
  expect(resolveErrorDetail(err)).toBe('HTTP 503 · unavailable')
  expect(resolveErrorDetail(new Error('network'))).toBeNull()
  expect(resolveErrorDetail(null)).toBeNull()
})

test('error outranks loading so a failed refresh does not spin forever', () => {
  render(<PageStatus loading error={{ error: 'It broke' }} />)

  expect(screen.getByRole('alert')).toHaveTextContent('It broke')
  expect(screen.queryByRole('status')).toBeNull()
})

test('error is assertive, loading is polite', () => {
  const { unmount } = render(<PageStatus error="bad" />)
  expect(screen.getByRole('alert')).toBeInTheDocument()
  unmount()

  render(<PageStatus loading />)
  const status = screen.getByRole('status')
  expect(status).toHaveAttribute('aria-busy', 'true')
  expect(status).toHaveAttribute('aria-live', 'polite')
  expect(status).toHaveClass('od-page-status--takeover')
  expect(status.querySelector('.od-page-status__spinner')).toBeInTheDocument()
})

test('retry is offered only when there is something to retry', () => {
  const onRetry = vi.fn()
  const { unmount } = render(<PageStatus error="bad" onRetry={onRetry} retryLabel="Again" />)
  screen.getByRole('button', { name: 'Again' }).click()
  expect(onRetry).toHaveBeenCalledTimes(1)
  unmount()

  render(<PageStatus error="bad" />)
  expect(screen.queryByRole('button')).toBeNull()
})

test('an explicit errorMessage wins over whatever the server said', () => {
  // Some pages deliberately translate a raw failure into operator guidance.
  render(<PageStatus error={{ error: 'ECONNREFUSED' }} errorMessage="Open System for details." />)

  expect(screen.getByRole('alert')).toHaveTextContent('Open System for details.')
  expect(screen.queryByText('ECONNREFUSED')).toBeNull()
})

test('idle renders its children and nothing of its own', () => {
  const { container } = render(
    <PageStatus>
      <p>real content</p>
    </PageStatus>,
  )

  expect(screen.getByText('real content')).toBeInTheDocument()
  expect(container.querySelector('.od-page-status')).toBeNull()
})

test('empty state is a status, and still renders children beneath it', () => {
  render(
    <PageStatus emptyMessage="Nothing here yet">
      <button type="button">Add one</button>
    </PageStatus>,
  )

  expect(screen.getByRole('status')).toHaveTextContent('Nothing here yet')
  expect(screen.getByRole('button', { name: 'Add one' })).toBeInTheDocument()
})
