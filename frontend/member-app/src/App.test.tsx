import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from './App'
import { ShellHarness } from './testShell'

vi.mock('./LibraryApp', () => ({ LibraryApp: () => <div>LibraryPage</div> }))
vi.mock('./DiscoverApp', () => ({ DiscoverApp: () => <div>DiscoverPage</div> }))
vi.mock('./FavoritesApp', () => ({ FavoritesApp: () => <div>FavoritesPage</div> }))
vi.mock('./pages/DownloadsPage', () => ({ DownloadsPage: () => <div>DownloadsPage</div> }))
// Chrome is stubbed so route assertions are not coupled to the rail's contents.
vi.mock('./chrome/SideRail', () => ({ SideRail: () => <nav>SideRail</nav> }))
vi.mock('./chrome/TopBar', () => ({ TopBar: () => <header>TopBar</header> }))
vi.mock('./chrome/CommandPalette', () => ({
  CommandPalette: () => null,
  buildPaletteCommands: () => [],
}))
vi.mock('./components/SocialCompanionDock', () => ({
  SocialCompanionDock: () => null,
}))
vi.mock('./components/ChatSlideOut', () => ({
  ChatSlideOut: () => null,
}))
vi.mock('./pages/NewsPage', () => ({
  NewsPage: () => (
    <div>
      <h1>News</h1>
    </div>
  ),
}))
// The real lazy page — it reads useShellConfig() itself now, so the mock does
// too, proving the provider chain reaches a routed page.
vi.mock('./pages/CollectionsPage', async () => {
  const { useShellConfig } = await vi.importActual<typeof import('@oneirodex/ui')>('@oneirodex/ui')
  return {
    CollectionsPage: () => <div>CollectionsPage:{String(useShellConfig().tileSize)}</div>,
  }
})

function renderAt(path: any, shell: any) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ShellHarness shell={shell}>
        <App />
      </ShellHarness>
    </MemoryRouter>,
  )
}

test('layout exposes skip link and main landmark', () => {
  renderAt('/library', { tileSize: 'M', isAdmin: false })
  const skip = screen.getByRole('link', { name: /skip to main content/i })
  expect(skip).toHaveAttribute('href', '#main-content')
  expect(document.getElementById('main-content')).toBeTruthy()
  expect(document.getElementById('main-content')!.tagName).toBe('MAIN')
})

test('renders library route', () => {
  renderAt('/library', { tileSize: 'M', isAdmin: false })
  expect(screen.getByText('LibraryPage')).toBeInTheDocument()
  // TopNav already labels the Library route — no redundant page H1 here.
  expect(screen.queryByRole('heading', { name: 'Library' })).not.toBeInTheDocument()
})

test('applies tile size CSS vars from shell config', () => {
  renderAt('/discover', { tileSize: 'L', isAdmin: false })
  // Legacy L → 75% → 252.5px (110 + 190*0.75)
  expect(document.documentElement.style.getPropertyValue('--od-tile-min')).toBe('252.5px')
  expect(screen.getByText('DiscoverPage')).toBeInTheDocument()
})

test('keeps the retired playromtest URL inside the member shell', () => {
  renderAt('/playromtest', { tileSize: 'M', isAdmin: false })
  expect(screen.getByText('DiscoverPage')).toBeInTheDocument()
  expect(screen.getByText('SideRail')).toBeInTheDocument()
  expect(screen.getByText('TopBar')).toBeInTheDocument()
  expect(document.getElementById('main-content')).toBeTruthy()
})

test('renders favorites route with tile size', () => {
  renderAt('/favorites', { tileSize: 'S', isAdmin: false })
  expect(screen.getByText('FavoritesPage')).toBeInTheDocument()
  // Legacy S → 25% → 157.5px (110 + 190*0.25)
  expect(document.documentElement.style.getPropertyValue('--od-tile-min')).toBe('157.5px')
})

test('renders downloads route', async () => {
  renderAt('/downloads', { tileSize: 'XL', isAdmin: false })
  expect(await screen.findByText('DownloadsPage')).toBeInTheDocument()
  expect(document.documentElement.style.getPropertyValue('--od-tile-min')).toBe('300px')
})

test('renders news more route', async () => {
  renderAt('/news', { tileSize: 'M', isAdmin: false })
  expect(await screen.findByRole('heading', { name: 'News' })).toBeInTheDocument()
})

test('renders collections route with the real page reading shell config from context', async () => {
  renderAt('/collections', { tileSize: 'M', isAdmin: false })
  expect(await screen.findByText('CollectionsPage:M')).toBeInTheDocument()
})
