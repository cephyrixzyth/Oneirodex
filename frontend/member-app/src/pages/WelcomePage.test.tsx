import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WelcomePage } from './WelcomePage'
import { ShellHarness } from '../testShell'
import { jsonResponse, stubFetch } from '../testJsonResponse'
import { connection, connectionsBody } from '../components/stores/storeFixtures'
import { storeSetupDismissed } from '../components/stores/StoreSetupPrompt'

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function renderWelcome() {
  return render(
    <ShellHarness shell={{ userId: 42 }} router initialEntries={['/welcome']}>
      <WelcomePage />
    </ShellHarness>,
  )
}

test('first-run uses the same list and points at the library when nothing is linked yet', async () => {
  stubFetch(() => jsonResponse(connectionsBody([connection('gog')])))
  renderWelcome()
  expect(await screen.findByRole('listitem', { name: 'GOG' })).toBeInTheDocument()
  // The shared list nests under the step headings rather than competing with them.
  expect(screen.getByRole('heading', { level: 2, name: '1. Link or import' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 3, name: 'Keep in sync' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 4, name: 'GOG' })).toBeInTheDocument()
  expect(screen.getByText(/titles show up here/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Go to the library' })).toHaveAttribute(
    'href',
    '/library',
  )
})

test('with matches recorded, first-run offers review and an owned-games library view', async () => {
  const user = userEvent.setup()
  stubFetch(() =>
    jsonResponse(
      connectionsBody([
        connection('steam', {
          state: 'connected',
          account: { connected: true, linked_at: null, updated_at: null },
          credential: { source: 'not_required', household_available: false },
          records: { owned: 30, matched: 12, needs_review: 3, last_recorded_at: null },
          actions: ['sync', 'reconnect', 'import_csv', 'disconnect'],
        }),
      ]),
    ),
  )
  renderWelcome()
  expect(await screen.findByText(/3 are not matched to a library game yet/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Review 3 titles' })).toHaveAttribute(
    'href',
    '/ownership?view=review',
  )
  const open = screen.getByRole('link', { name: 'Show games I own' })
  expect(open).toHaveAttribute('href', '/library?ownership=owned')
  await user.click(open)
  expect(storeSetupDismissed(42)).toBe(true)
})
