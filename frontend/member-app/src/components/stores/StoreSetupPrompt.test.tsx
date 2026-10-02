import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StoreSetupPrompt, dismissStoreSetup, storeSetupDismissed } from './StoreSetupPrompt'
import { ShellHarness } from '../../testShell'
import { jsonResponse, stubFetch } from '../../testJsonResponse'
import { connection, connectionsBody } from './storeFixtures'

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function renderPrompt() {
  return render(
    <ShellHarness shell={{ userId: 7 }} router>
      <StoreSetupPrompt />
    </ShellHarness>,
  )
}

test('invites a member with nothing linked or imported, and Not now remembers it', async () => {
  const user = userEvent.setup()
  stubFetch(() => jsonResponse(connectionsBody([connection('gog')])))
  renderPrompt()
  expect(await screen.findByRole('link', { name: 'Set up stores' })).toHaveAttribute(
    'href',
    '/welcome',
  )
  await user.click(screen.getByRole('button', { name: 'Not now' }))
  expect(screen.queryByRole('link', { name: 'Set up stores' })).toBeNull()
  expect(storeSetupDismissed(7)).toBe(true)
})

test('stays out of the way once something is recorded, when dismissed, or on errors', async () => {
  const fetchMock = stubFetch(() =>
    jsonResponse(
      connectionsBody([
        connection('gog', {
          records: { owned: 3, matched: 1, needs_review: 0, last_recorded_at: null },
        }),
      ]),
    ),
  )
  const first = renderPrompt()
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(screen.queryByRole('link', { name: 'Set up stores' })).toBeNull()
  first.unmount()

  dismissStoreSetup(7)
  fetchMock.mockClear()
  const second = renderPrompt()
  expect(fetchMock).not.toHaveBeenCalled()
  second.unmount()

  window.localStorage.clear()
  stubFetch(() =>
    jsonResponse({ ok: false, error: 'x', error_code: 'internal' }, { ok: false, status: 500 }),
  )
  renderPrompt()
  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(screen.queryByRole('link', { name: 'Set up stores' })).toBeNull()
})
