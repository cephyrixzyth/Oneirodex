import { render, screen } from '@testing-library/react'
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
  const fetch = stubFetch((_input, init) => {
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
  await user.click(screen.getByRole('button', { name: /submit ticket/i }))

  expect(await screen.findByText(/Ticket #17 saved/i)).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledTimes(1)
})
