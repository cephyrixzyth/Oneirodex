import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { SupportInboxPage } from './SupportInboxPage'

function mockFetch(tickets: any) {
  return vi.fn(async (): Promise<any> => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => ({ tickets }),
  }))
}

/**
 * The Support readiness strip (UID-014).
 *
 * Open is the count that decides whether this page needs anyone's attention,
 * so it is the one that carries a tone. These pin that open and resolved are
 * counted from the ticket list rather than tracked separately — a second piece
 * of state would be one more thing to keep in step with the rows it describes.
 */
test('counts open, resolved and GitHub-synced tickets', async () => {
  const originalFetch = globalThis.fetch
  // Counts chosen so all three differ — open 3, resolved 1, synced 2. With two
  // tiles showing the same number a getByText would match both and throw,
  // which says nothing about whether the right tile holds the right value.
  globalThis.fetch = mockFetch([
    { id: 1, status: 'open', title: 'A', github_issue_number: 11 },
    { id: 2, status: 'open', title: 'B' },
    { id: 3, status: 'open', title: 'C', github_issue_number: 13 },
    { id: 4, status: 'resolved', title: 'D' },
  ]) as unknown as typeof globalThis.fetch
  try {
    render(<SupportInboxPage />)

    const strip = await screen.findByLabelText('Support')
    expect(within(strip).getByText('Open')).toBeInTheDocument()
    expect(within(strip).getByText('3')).toBeInTheDocument() // three open
    expect(within(strip).getByText('1')).toBeInTheDocument() // one resolved
    expect(within(strip).getByText('2')).toBeInTheDocument() // two on GitHub
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('an empty inbox is a good state, not an empty one', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch([]) as unknown as typeof globalThis.fetch
  try {
    render(<SupportInboxPage />)

    // MetricStrip drops rows whose value is undefined, so a zero count has to
    // stay a rendered zero — "no open tickets" is the answer someone came for,
    // and a strip that vanished would read as the page failing to load.
    const strip = await screen.findByLabelText('Support')
    expect(within(strip).getByText('Open')).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

function jsonResponse(body: any, status = 200) {
  return {
    ok: status < 400,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async () => JSON.stringify(body),
    json: async () => body,
  }
}
afterEach(() => vi.unstubAllGlobals())

test('failed loading stops progress, retains title and retries', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ error: 'Inbox unavailable' }, 503))
      .mockResolvedValueOnce(jsonResponse({ tickets: [] })),
  )
  render(<SupportInboxPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Inbox unavailable')
  expect(screen.getByRole('heading', { name: 'Support inbox' })).toBeInTheDocument()
  expect(document.querySelector('[aria-busy="true"]')).toBeNull()
  expect(screen.queryByLabelText('Support')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByText('No tickets yet.')).toBeInTheDocument()
  expect(screen.getByRole('table', { name: 'Support tickets' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Support tickets table' })).toHaveAttribute(
    'tabindex',
    '0',
  )
})

test('resolve uses shared transport, blocks repeat actions and refreshes the list', async () => {
  const user = userEvent.setup()
  let release!: (value: any) => void
  let resolved = false
  const fetcher = vi.fn((_url, init) => {
    if (init?.method === 'POST')
      return new Promise((resolve) => {
        release = resolve
      })
    return Promise.resolve(
      jsonResponse({
        tickets: [{ id: 7, title: 'Review ticket', status: resolved ? 'resolved' : 'open' }],
      }),
    )
  })
  vi.stubGlobal('fetch', fetcher)
  render(<SupportInboxPage />)
  const button = await screen.findByRole('button', { name: 'Resolve Review ticket' })
  await user.click(button)
  expect(button).toBeDisabled()
  await user.click(button)
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect(fetcher.mock.calls.find(([, init]) => init?.method === 'POST')?.[0]).toBe(
    '/api/support/tickets/7/resolve',
  )
  resolved = true
  release(jsonResponse({ ok: true }))
  expect(await screen.findByText('resolved')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Resolve Review ticket' })).not.toBeInTheDocument()
})

test('resolve failure is visible and retains the ticket', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn((_url, init) =>
      Promise.resolve(
        jsonResponse(
          init?.method === 'POST'
            ? { error: 'Resolve unavailable', ok: false }
            : { tickets: [{ id: 9, title: 'Unchanged ticket', status: 'open' }] },
          init?.method === 'POST' ? 503 : 200,
        ),
      ),
    ),
  )
  render(<SupportInboxPage />)
  await user.click(await screen.findByRole('button', { name: 'Resolve Unchanged ticket' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Resolve unavailable')
  expect(screen.getByRole('button', { name: 'Resolve Unchanged ticket' })).toBeEnabled()
})
