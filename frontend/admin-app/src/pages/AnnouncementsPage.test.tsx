import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { AnnouncementsPage } from './AnnouncementsPage'

/**
 * First coverage for this page (GT-B33).
 *
 * It had none, which is why converting its status blocks to the shared
 * `PageStatus` was an unguarded change: the full admin suite would not have
 * caught a render break here because nothing rendered it.
 */

function mockList(announcements: any, { fail = false } = {}) {
  const headers = new Headers({ 'content-type': 'application/json' })
  globalThis.fetch = vi.fn(async () => {
    if (fail) return { ok: false, status: 500, headers, json: async () => ({ error: 'Boom' }) }
    return { ok: true, status: 200, headers, json: async () => ({ announcements }) }
  }) as unknown as typeof globalThis.fetch
}

afterEach(() => {
  vi.restoreAllMocks()
})

test('shows the shared loading block before the list arrives', () => {
  // Never resolves — the page should be reporting progress, not blank.
  globalThis.fetch = vi.fn(() => new Promise(() => {})) as unknown as typeof globalThis.fetch
  render(<AnnouncementsPage />)

  const status = screen.getByRole('status')
  expect(status).toHaveTextContent(/loading announcements/i)
  expect(status).toHaveAttribute('aria-busy', 'true')
})

test('an empty list is a status, not a bare paragraph', async () => {
  // Was `<p>No announcements yet.</p>` — visually and semantically unlike the
  // empty state every other admin page shows.
  mockList([])
  render(<AnnouncementsPage />)

  await waitFor(() => {
    expect(screen.getByText(/no announcements yet/i)).toBeInTheDocument()
  })
  expect(screen.getByRole('status')).toHaveTextContent(/no announcements yet/i)
})

test('a failed load is announced assertively', async () => {
  mockList(null, { fail: true })
  render(<AnnouncementsPage />)

  // role="alert", not a polite status: the page has no content to fall back on.
  await waitFor(() => {
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

test('lists what it loaded', async () => {
  mockList([{ id: 1, title: 'Server maintenance', body: 'Sunday 02:00', published: true }])
  render(<AnnouncementsPage />)

  await waitFor(() => {
    expect(screen.getByText('Server maintenance')).toBeInTheDocument()
  })
  expect(screen.queryByText(/no announcements yet/i)).toBeNull()
})

test('keeps an accessible document title without a visible heading above the legacy-aligned form', () => {
  globalThis.fetch = vi.fn(() => new Promise(() => {})) as unknown as typeof globalThis.fetch
  render(<AnnouncementsPage />)

  const heading = screen.getByRole('heading', { name: 'Announcements', level: 1 })
  expect(heading).toHaveClass('visually-hidden')
  expect(heading).toHaveTextContent('Announcements')
  expect(document.title).toBe('Announcements · Oneirodex Admin')
})
