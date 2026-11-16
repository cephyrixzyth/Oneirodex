/**
 * TC-3 (v11 H-T): a thin seat is never offered a companion action it cannot
 * finish. GameActionBar and BigPicture already say so (UID-061); these are
 * the other surfaces that used to leak "Apply with companion" / open-path /
 * per-update download when the member's companion happened to be online.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { DetailsVersionsSection } from '../pages/gameDetails/DetailsVersionsSection'
import { DetailsTranslationsSection } from '../pages/gameDetails/DetailsTranslationsSection'
import { OpenPathModal } from './OpenPathModal'
import { WaysToPlayPage } from '../pages/WaysToPlayPage'
import { queueClientCommand } from '../api/clientCommands'

vi.mock('../api/clientCommands', () => ({ queueClientCommand: vi.fn(async () => ({})) }))
vi.mock('@oneirodex/ui', async (io) => ({
  ...(await io<typeof import('@oneirodex/ui')>()),
  useShellConfig: () => ({ enableVr: false }),
}))

const game: any = {
  uuid: 'g-1',
  name: 'Demo',
  client_connected: true,
  rom_patch_apply_enabled: true,
  translation_patches: [
    {
      uuid: 'p-1',
      label: 'English patch',
      language: 'en',
      source_url: 'https://example.test/guide',
    },
  ],
}
const updateRow: any = {
  uuid: 'v-2',
  kind: 'update',
  label: 'Patch 1.03',
  download_url: '/dl/v-2',
  size: 1024,
  path_ok: true,
}
const noop = () => {}
const actions: any = {
  busyVersionKey: null,
  setBusyVersionKey: noop,
  versionActionStatus: null,
  setVersionActionStatus: noop,
  cleanupBusy: false,
  handleCleanupOrphans: async () => {},
  handleVersionDownload: async () => {},
}

function seat(mode: string | null) {
  if (mode) sessionStorage.setItem('oneirodex-seat', mode)
  else sessionStorage.removeItem('oneirodex-seat')
}

afterEach(() => {
  seat(null)
  vi.mocked(queueClientCommand).mockClear()
})

test('Versions: a thin seat gets the note, not Apply / per-update Download', () => {
  seat('thin')
  render(
    <DetailsVersionsSection
      game={game}
      baseAndUpdates={[updateRow]}
      hasMissingVersions={false}
      {...actions}
    />,
  )
  expect(screen.getByText(/happen on the desktop companion/)).toHaveAttribute('data-seat', 'thin')
  expect(screen.queryByRole('button', { name: /Apply with companion/ })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Download' })).toBeNull()
})

test('Versions: a browser seat with a connected companion still offers Apply', () => {
  seat('browser')
  render(
    <DetailsVersionsSection
      game={game}
      baseAndUpdates={[updateRow]}
      hasMissingVersions={false}
      {...actions}
    />,
  )
  expect(screen.getByRole('button', { name: /Apply with companion/ })).toBeInTheDocument()
  expect(screen.queryByText(/happen on the desktop companion/)).toBeNull()
})

test('Translations: a thin seat keeps the Guide link and loses the queue button', () => {
  seat('thin')
  render(
    <MemoryRouter>
      <DetailsTranslationsSection
        game={game}
        busyVersionKey={null}
        setBusyVersionKey={noop}
        setVersionActionStatus={noop}
        setRetryCount={noop}
      />
    </MemoryRouter>,
  )
  expect(screen.queryByRole('button', { name: /Apply with companion/ })).toBeNull()
  expect(screen.getByRole('link', { name: 'Guide' })).toBeInTheDocument()
})

test('Translations: a non-HTTP(S) guide URL is not rendered as a link', () => {
  seat('thin')
  render(
    <MemoryRouter>
      <DetailsTranslationsSection
        game={{
          ...game,
          translation_patches: [
            { uuid: 'p-unsafe', label: 'Unsafe patch', source_url: 'javascript:alert(1)' },
          ],
        }}
        busyVersionKey={null}
        setBusyVersionKey={noop}
        setVersionActionStatus={noop}
        setRetryCount={noop}
      />
    </MemoryRouter>,
  )
  expect(screen.queryByRole('link', { name: 'Guide' })).toBeNull()
})

test('Open path: a thin seat copies the path and never queues open_path', async () => {
  seat('thin')
  const user = userEvent.setup()
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn(async () => {}) },
    configurable: true,
  })
  render(
    <OpenPathModal
      open
      onClose={noop}
      path="D:\Games\Demo"
      gameUuid="g-1"
      clientConnected
      label="Demo"
    />,
  )
  await user.click(screen.getByRole('button', { name: /open in file explorer/i }))
  expect(queueClientCommand).not.toHaveBeenCalled()
  expect(await screen.findByText(/this seat only browses/)).toBeInTheDocument()
})

test('Ways to play: the companion card says the launch is elsewhere on a thin seat', () => {
  seat('thin')
  render(
    <MemoryRouter>
      <WaysToPlayPage />
    </MemoryRouter>,
  )
  const card = screen.getByRole('link', { name: /Companion/ })
  expect(card).toHaveAttribute('data-seat', 'thin')
  expect(card).toHaveTextContent(/not on this seat/)
})
