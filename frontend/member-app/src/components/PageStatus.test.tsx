import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { PageStatus, resolveErrorMessage, resolveErrorDetail } from './PageStatus'

// Deliberately a *retired* id. GT-B23 replaced the six abstract motifs with
// console hardware, and 'orbit' is one of the ids that went — LoadingMotif maps
// it forward via LEGACY_MOTIF_ALIASES so a member who picked it years ago still
// gets a spinner instead of nothing. Mocking a live id would test less.
vi.mock('./loadingMotifApi', () => ({
  useLoadingMotifId: () => 'orbit',
}))

test('loading state sets aria-busy and shows loading message', () => {
  render(<PageStatus loading loadingMessage="Loading Discover…" />)
  const status = screen.getByRole('status')
  expect(status).toHaveAttribute('aria-busy', 'true')
  expect(status).toHaveClass('od-page-status--takeover')
  expect(screen.getByText('Loading Discover')).toBeInTheDocument()
  expect(status.textContent).toMatch(/Loading Discover\s+\.{1,3}/)
  expect(screen.getByRole('img')).toHaveAttribute('data-motif', 'disc')
})

test('nested loading stays inline instead of taking over the page', () => {
  render(<PageStatus loading inline loadingMessage="Loading rooms…" />)
  const status = screen.getByRole('status')
  expect(status).not.toHaveClass('od-page-status--takeover')
  expect(screen.getByText('Loading rooms')).toBeInTheDocument()
})

test('emptyMessage renders polite empty status', () => {
  render(<PageStatus emptyMessage="No channels yet." />)
  expect(screen.getByRole('status')).not.toHaveAttribute('aria-busy', 'true')
  expect(screen.getByText('No channels yet.')).toBeInTheDocument()
})

test('idle with children passes through', () => {
  render(
    <PageStatus>
      <p>Ready content</p>
    </PageStatus>,
  )
  expect(screen.getByText('Ready content')).toBeInTheDocument()
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

// --- GT-A2 error state -----------------------------------------------------

test('error renders an assertive alert, not a polite status', () => {
  render(<PageStatus error={{ error: 'Admin required' }} />)
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(screen.getByText('Admin required')).toBeInTheDocument()
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('error outranks loading so a failed refresh stops spinning', () => {
  render(<PageStatus loading error={{ error: 'Upstream down' }} />)
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
})

test('retry button fires onRetry', async () => {
  const onRetry = vi.fn()
  render(<PageStatus error={{ error: 'Timed out' }} onRetry={onRetry} />)
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(onRetry).toHaveBeenCalledTimes(1)
})

test('no retry affordance when no handler is supplied', () => {
  render(<PageStatus error={{ error: 'Timed out' }} />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test('operator detail is shown separately from the headline', () => {
  render(<PageStatus error={{ error: 'Game not found', status: 404, error_code: 'not_found' }} />)
  expect(screen.getByText('Game not found')).toBeInTheDocument()
  expect(screen.getByText('HTTP 404 · not_found')).toBeInTheDocument()
})

// --- envelope tolerance ----------------------------------------------------

test('resolveErrorMessage accepts every shape still in the tree', () => {
  expect(resolveErrorMessage('plain string')).toBe('plain string')
  expect(resolveErrorMessage({ error: 'legacy error key' })).toBe('legacy error key')
  expect(resolveErrorMessage({ message: 'legacy message key' })).toBe('legacy message key')
  expect(resolveErrorMessage({ error: { message: 'nested' } })).toBe('nested')
  expect(resolveErrorMessage(new Error('thrown'))).toBe('thrown')
})

test('resolveErrorMessage falls back rather than rendering an object', () => {
  expect(resolveErrorMessage({})).toBe('Something went wrong.')
  expect(resolveErrorMessage({ error: '   ' })).toBe('Something went wrong.')
  expect(resolveErrorMessage(null)).toBe('Something went wrong.')
})

test('resolveErrorDetail is null when there is nothing operator-useful', () => {
  expect(resolveErrorDetail({ error: 'x' })).toBeNull()
  expect(resolveErrorDetail(new Error('x'))).toBeNull()
})
