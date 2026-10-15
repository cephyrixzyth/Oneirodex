import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { InvitesPage } from './InvitesPage'
import { SupportInboxPage } from './SupportInboxPage'

/**
 * Coverage for the three admin tables migrated onto DataTable (UX-C8).
 *
 * These pages had **no tests at all** before the migration, so nothing verified
 * they still rendered after being rewritten.
 */

const INVITES = {
  users: [
    { user_id: 'u1', name: 'Zoe', role: 'admin', invite_quota: 5, unused_invites: 2 },
    { user_id: 'u2', name: 'Adam', role: 'user', invite_quota: 20, unused_invites: 0 },
  ],
}

const TICKETS = {
  tickets: [
    {
      id: 2,
      severity: 'high',
      area: 'scan',
      title: 'Scan stalls',
      status: 'open',
      github_sync: 'off',
    },
    {
      id: 1,
      severity: 'low',
      area: 'ui',
      title: 'Badge overlaps',
      status: 'resolved',
      github_sync: 'off',
    },
  ],
}

function mockFetch(payload: any) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (): Promise<any> => ({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),

      text: async function () {
        return JSON.stringify(await this.json())
      },
      json: async () => payload,
    })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function bodyFirstCells() {
  const body = screen.getAllByRole('rowgroup')[1]
  return within(body)
    .getAllByRole('row')
    .map((row) => within(row).getAllByRole('cell')[0].textContent)
}

test('invites table renders rows and can sort by name', async () => {
  mockFetch(INVITES)
  render(<InvitesPage />)

  await waitFor(() => expect(bodyFirstCells()).toEqual(['Zoe', 'Adam']))

  fireEvent.click(screen.getByRole('button', { name: /Name/ }))
  expect(bodyFirstCells()).toEqual(['Adam', 'Zoe'])
})

test('invites table filters rows', async () => {
  mockFetch(INVITES)
  render(<InvitesPage />)
  await waitFor(() => expect(bodyFirstCells()).toEqual(['Zoe', 'Adam']))

  fireEvent.change(screen.getByLabelText(/Filter table rows/i), { target: { value: 'adam' } })
  expect(bodyFirstCells()).toEqual(['Adam'])
})

test('support inbox renders tickets and sorts numerically by id', async () => {
  mockFetch(TICKETS)
  render(<SupportInboxPage />)

  expect(await screen.findByText('Scan stalls')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: /ID/ }))
  expect(bodyFirstCells()).toEqual(['1', '2'])
})

test('support inbox keeps the Resolve action only on open tickets', async () => {
  mockFetch(TICKETS)
  render(<SupportInboxPage />)
  await screen.findByText('Scan stalls')

  // One open ticket in the fixture, so exactly one Resolve button.
  expect(screen.getAllByRole('button', { name: 'Resolve Scan stalls' })).toHaveLength(1)
})

test('empty invites state is honest rather than a blank table', async () => {
  mockFetch({ users: [] })
  render(<InvitesPage />)
  await waitFor(() => {
    expect(screen.getByText(/No users\./i)).toBeInTheDocument()
  })
})
