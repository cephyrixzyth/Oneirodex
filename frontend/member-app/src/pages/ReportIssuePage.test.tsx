import { act, render, screen, within } from '@testing-library/react'
// Module scope, not inside the test: see SpaceRail.test.jsx — an in-test
// dynamic import puts the module's first transform inside the timeout.
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { expect, test } from 'vitest'
import { jsonResponse, stubFetch } from '../testJsonResponse'
import { ReportIssuePage } from './ReportIssuePage'

test('keeps logs and context collapsed by default', () => {
  render(
    <MemoryRouter>
      <ReportIssuePage />
    </MemoryRouter>,
  )

  // "Report", not "Report issue": the form takes ideas as well as defects now.
  expect(screen.getByRole('heading', { name: 'Report' })).toBeInTheDocument()
  expect(screen.queryByText(/Files a ticket for maintainers/i)).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: /What happened/i })).not.toBeInTheDocument()
  expect(screen.getByRole('radio', { name: /Something is broken/ })).toBeChecked()
  expect(screen.getByRole('radio', { name: /An idea/ })).not.toBeChecked()
  expect(
    screen.getByRole('checkbox', { name: /Also send this report to GitHub/i }),
  ).not.toBeChecked()
  expect(screen.getByLabelText('Title')).toBeInTheDocument()
  expect(screen.getByLabelText('Symptom')).toBeInTheDocument()

  const logsFold = screen.getByText('Logs & extras (optional)').closest('details')
  const contextFold = screen.getByText('Context (deploy, client, URL)').closest('details')
  expect(logsFold).toBeTruthy()
  expect(contextFold).toBeTruthy()
  expect(logsFold!.open).toBe(false)
  expect(contextFold!.open).toBe(false)

  expect(screen.queryByPlaceholderText('Paste only the relevant lines')).not.toBeInTheDocument()
})

test('expands logs fold when opened', async () => {
  const user = userEvent.setup()

  render(
    <MemoryRouter>
      <ReportIssuePage />
    </MemoryRouter>,
  )

  await user.click(screen.getByText('Logs & extras (optional)'))
  expect(screen.getByPlaceholderText('Paste only the relevant lines')).toBeInTheDocument()
})

test('submit failure uses PageStatus', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn(() => jsonResponse({ error: 'Submit failed' }, { ok: false, status: 500 })),
  )

  render(
    <MemoryRouter>
      <ReportIssuePage />
    </MemoryRouter>,
  )

  await user.type(screen.getByLabelText('Title'), 'Broken tiles')
  await user.type(screen.getByLabelText('Symptom'), 'Covers are blank')
  await user.click(screen.getByRole('button', { name: /submit ticket/i }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Submit failed')
  vi.unstubAllGlobals()
})

test('GitHub sync is sent only after the member opts in', async () => {
  const user = userEvent.setup()
  const fetch = stubFetch((input, init) => {
    if (String(input).endsWith('/preview'))
      return jsonResponse({
        preview: {
          available: true,
          destination: 'example-owner/example-repo',
          visibility: 'unknown',
          title: 'Preview',
          body: 'Redacted report',
          request_id: 'preview-request',
          preview_token: 'approved',
        },
      })
    expect(JSON.parse(init.body).sync_to_github).toBe(true)
    return jsonResponse(
      { ok: true, ticket: { id: 17, github_sync: 'local_only' } },
      { status: 201 },
    )
  })

  render(
    <MemoryRouter>
      <ReportIssuePage />
    </MemoryRouter>,
  )

  await user.type(screen.getByLabelText('Title'), 'Private context')
  await user.type(screen.getByLabelText('Symptom'), 'Please keep this local unless I opt in')
  await user.click(screen.getByRole('checkbox', { name: /Also send this report to GitHub/i }))
  await user.click(screen.getByRole('button', { name: /preview github report/i }))
  await screen.findByText('Redacted report')
  await user.click(screen.getByRole('button', { name: /submit ticket/i }))

  expect(await screen.findByText(/Ticket #17 saved/i)).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls.filter(([input]) => String(input).endsWith('/tickets'))).toHaveLength(1)
})

test('editing during a pending preview discards its late approval', async () => {
  const user = userEvent.setup()
  let resolvePreview!: (value: any) => void
  stubFetch(
    () =>
      new Promise((resolve) => {
        resolvePreview = resolve
      }),
  )
  render(
    <MemoryRouter>
      <ReportIssuePage />
    </MemoryRouter>,
  )
  await user.type(screen.getByLabelText('Title'), 'Before preview')
  await user.type(screen.getByLabelText('Symptom'), 'Original')
  await user.click(screen.getByRole('checkbox', { name: /Also send this report to GitHub/i }))
  await user.click(screen.getByRole('button', { name: /preview github report/i }))
  await user.type(screen.getByLabelText('Symptom'), ' edited')
  await act(async () =>
    resolvePreview(
      await jsonResponse({
        preview: {
          available: true,
          destination: 'example-owner/example-repo',
          title: 'Stale preview',
          body: 'Stale body',
          preview_token: 'stale',
          request_id: 'stale',
        },
      }),
    ),
  )
  expect(screen.queryByText('Stale body')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /submit ticket/i })).toBeDisabled()
})

test('unconfigured GitHub preview leaves local-only submission available', async () => {
  const user = userEvent.setup()
  const fetch = stubFetch((input, init) => {
    if (String(input).endsWith('/preview')) return jsonResponse({ preview: { available: false } })
    expect(JSON.parse(init.body).sync_to_github).toBe(false)
    return jsonResponse({ ticket: { id: 72, github_sync: 'local_only' } }, { status: 201 })
  })
  render(
    <MemoryRouter>
      <ReportIssuePage />
    </MemoryRouter>,
  )
  await user.type(screen.getByLabelText('Title'), 'Local-only still works')
  await user.type(screen.getByLabelText('Symptom'), 'Details')
  await user.click(screen.getByRole('checkbox', { name: /Also send this report to GitHub/i }))
  await user.click(screen.getByRole('button', { name: /preview github report/i }))
  await screen.findByText(/GitHub forwarding is unavailable/)
  expect(screen.getByRole('button', { name: /submit ticket/i })).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: /Also send this report to GitHub/i }))
  await user.click(screen.getByRole('button', { name: /submit ticket/i }))
  expect(await screen.findByText(/Ticket #72 saved/)).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledTimes(2)
})

test('requires the server-redacted preview and destination before forwarding', async () => {
  const user = userEvent.setup()
  const fetch = stubFetch((input, init) => {
    if (String(input).endsWith('/preview'))
      return jsonResponse({
        preview: {
          available: true,
          destination: 'example-owner/example-repo',
          visibility: 'unknown',
          redaction: 'mandatory',
          title: 'Redacted title',
          body: 'api_key=[REDACTED]',
          request_id: 'preview-request',
          preview_token: 'approved-preview',
        },
      })
    expect(JSON.parse(init.body).preview_token).toBe('approved-preview')
    expect(JSON.parse(init.body).request_id).toBe('preview-request')
    return jsonResponse({ ticket: { id: 71, github_sync: 'synced' } }, { status: 201 })
  })
  render(
    <MemoryRouter>
      <ReportIssuePage />
    </MemoryRouter>,
  )
  await user.type(screen.getByLabelText('Title'), 'Sensitive report')
  await user.type(screen.getByLabelText('Symptom'), 'Details')
  await user.click(screen.getByRole('checkbox', { name: /Also send this report to GitHub/i }))
  expect(screen.getByRole('button', { name: /submit ticket/i })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: /preview github report/i }))
  const preview = await screen.findByRole('region', { name: 'GitHub report preview' })
  expect(within(preview).getByText('example-owner/example-repo')).toBeInTheDocument()
  expect(within(preview).getByText(/visibility is unknown/i)).toBeInTheDocument()
  expect(within(preview).getByText('api_key=[REDACTED]')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /submit ticket/i }))
  expect(await screen.findByText(/Ticket #71 saved/)).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledTimes(2)
})
