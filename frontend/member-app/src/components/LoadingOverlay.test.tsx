import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { LoadingOverlay } from './LoadingOverlay'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

function advance(ms: any) {
  act(() => {
    vi.advanceTimersByTime(ms)
  })
}

test('stays hidden while inactive', () => {
  render(<LoadingOverlay active={false} />)
  advance(1000)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('does not flash for work that finishes inside the delay', () => {
  const { rerender } = render(<LoadingOverlay active delayMs={250} />)
  advance(200)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()

  rerender(<LoadingOverlay active={false} delayMs={250} />)
  advance(500)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('appears once work outlasts the delay', () => {
  render(<LoadingOverlay active delayMs={250} label="Scanning…" />)
  advance(300)
  const status = screen.getByRole('status')
  expect(status).toBeInTheDocument()
  expect(status).toHaveTextContent('Scanning…')
})

test('announces politely so it does not interrupt a screen reader', () => {
  render(<LoadingOverlay active delayMs={0} />)
  advance(10)
  expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
})

test('delayMs 0 shows immediately, without waiting a tick', () => {
  // Initial page loads have nothing on screen yet — a blank panel with no
  // explanation is worse than an indicator that appears at once.
  render(<LoadingOverlay active delayMs={0} label="Loading…" />)
  expect(screen.getByRole('status')).toHaveTextContent('Loading…')
  expect(screen.getByRole('status').querySelector('.od-page-status__spinner')).toBeInTheDocument()
})

test('only dims the page when explicitly blocking', () => {
  const { container, rerender } = render(<LoadingOverlay active delayMs={0} />)
  advance(10)
  expect(container.querySelector('.od-loading-overlay--blocking')).toBeNull()

  rerender(<LoadingOverlay active delayMs={0} blocking />)
  advance(10)
  expect(container.querySelector('.od-loading-overlay--blocking')).not.toBeNull()
})

test('hides again when work completes', () => {
  const { rerender } = render(<LoadingOverlay active delayMs={0} />)
  advance(10)
  expect(screen.getByRole('status')).toBeInTheDocument()

  rerender(<LoadingOverlay active={false} delayMs={0} />)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})
