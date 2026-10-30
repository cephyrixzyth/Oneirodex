import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ShellConfigProvider, ViewerProvider, viewerFromConfig } from '@oneirodex/ui'
import { App } from './App'
import { installUnauthorizedRedirect } from './api/http'
import { GameDetailsApp, parseGameDetailsRootConfig } from './GameDetailsApp'

// Wave B1.3: one QueryClient for the whole member SPA. `useResource`
// (`@oneirodex/ui`) is the read path that consumes it; pages provide the
// provider, react-query provides caching + dedupe + refetch. Defaults are
// deliberately conservative — a 30s freshness window so route revisits do not
// re-hit the API, a single retry, and no refetch-on-focus (the member app is a
// long-lived tab, not a dashboard).
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export type CatalogFilters = Record<string, unknown>

export interface LibraryRootConfig {
  perPage: number
  defaultSort: string | undefined
  defaultSortOrder: string | undefined
  isAdmin: boolean
  showPlayStatus: boolean
  libraryCount: number
  gamesCount: number
  scanHasRun: boolean
  unmatchedCount: number
  enableDeleteOnDisk: boolean
  locale: string
  currentFilters: CatalogFilters
}

export interface FavoritesRootConfig {
  isAdmin: boolean
  showPlayStatus: boolean
}

export interface DiscoverRootConfig {
  isAdmin: boolean
}

export interface MemberShellConfig {
  [key: string]: unknown
  tileSize: string
  isAdmin: boolean
  isLibrarian: boolean
  role: string
  userId: number | null
  showTrailers: boolean
  showHelp: boolean
  enableVr: boolean
  enableActivity: boolean
  enableNewChrome: boolean
  showPlayStatus: boolean
  showTileTitles: boolean
  sourceUrl: string
  appVersion: string
  username: string
  avatar: string
  locale: string
  perPage: number
  defaultSort: string
  defaultSortOrder: string
  libraryCount: number
  gamesCount: number
  scanHasRun: boolean
  unmatchedCount: number
  enableDeleteOnDisk: boolean
  currentFilters: CatalogFilters
}

function parseFilters(raw: string | undefined): CatalogFilters {
  try {
    const parsed: unknown = JSON.parse(raw || '{}')
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as CatalogFilters
    }
  } catch {
    // fall through
  }
  return {}
}

export function parseRootConfig(rootElement: HTMLElement): LibraryRootConfig {
  return {
    perPage: Number(rootElement.dataset.perPage),
    defaultSort: rootElement.dataset.defaultSort,
    defaultSortOrder: rootElement.dataset.defaultSortOrder,
    isAdmin: rootElement.dataset.isAdmin === 'true',
    showPlayStatus: rootElement.dataset.showPlayStatus === 'true',
    libraryCount: Number(rootElement.dataset.libraryCount),
    gamesCount: Number(rootElement.dataset.gamesCount),
    // Why the catalog is empty, not just that it is (UID-043).
    scanHasRun: rootElement.dataset.scanHasRun === '1',
    unmatchedCount: Number(rootElement.dataset.unmatchedCount) || 0,
    enableDeleteOnDisk: rootElement.dataset.enableDeleteOnDisk === 'true',
    locale: rootElement.dataset.locale || 'en',
    currentFilters: parseFilters(rootElement.dataset.currentFilters),
  }
}

export function parseFavoritesRootConfig(rootElement: HTMLElement): FavoritesRootConfig {
  return {
    isAdmin: rootElement.dataset.isAdmin === 'true',
    showPlayStatus: rootElement.dataset.showPlayStatus === 'true',
  }
}

export function parseDiscoverRootConfig(rootElement: HTMLElement): DiscoverRootConfig {
  return {
    isAdmin: rootElement.dataset.isAdmin === 'true',
  }
}

export function parseShellConfig(rootElement: HTMLElement): MemberShellConfig {
  const currentFilters = parseFilters(rootElement.dataset.currentFilters)

  return {
    tileSize: rootElement.dataset.tileSize || 'M',
    isAdmin: rootElement.dataset.isAdmin === 'true',
    isLibrarian: rootElement.dataset.isLibrarian === 'true',
    role: rootElement.dataset.role || 'user',
    userId: rootElement.dataset.userId ? Number(rootElement.dataset.userId) : null,
    showTrailers: rootElement.dataset.showTrailers === 'true',
    showHelp: rootElement.dataset.showHelp === 'true',
    enableVr: rootElement.dataset.enableVr === 'true',
    // Absent attribute means an older shell render — default on rather than
    // hiding a surface that has always been there.
    enableActivity: rootElement.dataset.enableActivity !== 'false',
    // Two-bar chrome is on unless an operator explicitly sets false.
    enableNewChrome: rootElement.dataset.enableNewChrome !== 'false',
    showPlayStatus: rootElement.dataset.showPlayStatus === 'true',
    // Titles under catalog covers. Absent attribute means an older shell
    // render, and the strip is the default, so only an explicit false hides it.
    showTileTitles: rootElement.dataset.showTileTitles !== 'false',
    // AGPL §13 source offer — see config.ONEIRODEX_SOURCE_URL. A modified deployment
    // owes its users *its* source, so this is configuration, not a constant.
    sourceUrl: rootElement.dataset.sourceUrl || '',
    appVersion: rootElement.dataset.appVersion || '',
    username: rootElement.dataset.username || '',
    avatar: rootElement.dataset.avatar || '',
    locale: rootElement.dataset.locale || 'en',
    perPage: Number(rootElement.dataset.perPage) || 50,
    defaultSort: rootElement.dataset.defaultSort || 'name',
    defaultSortOrder: rootElement.dataset.defaultSortOrder || 'asc',
    libraryCount: Number(rootElement.dataset.libraryCount) || 0,
    gamesCount: Number(rootElement.dataset.gamesCount) || 0,
    scanHasRun: rootElement.dataset.scanHasRun === '1',
    unmatchedCount: Number(rootElement.dataset.unmatchedCount) || 0,
    enableDeleteOnDisk: rootElement.dataset.enableDeleteOnDisk === 'true',
    currentFilters,
  }
}

// Session expiry -> /login for every member `/api/...` call, in one place
// (mirrors admin-app's adminApi.js). Safe to call unconditionally: it is a
// no-op outside the browser and idempotent.
installUnauthorizedRedirect()

const memberAppRoot = document.getElementById('member-app-root')
if (memberAppRoot) {
  // UIR-3: mark the document so shared CSS can retire page titles without every
  // page needing an edit. On <html> rather than the SPA root so Jinja admin can
  // set the same attribute server-side and get the identical treatment.
  if (memberAppRoot.dataset.enableNewChrome !== 'false') {
    document.documentElement.dataset.chrome = 'v2'
  }
  const shellConfig = parseShellConfig(memberAppRoot)
  // Wave B1.6: identity + the rest of the bootstrap are provided once here, so
  // `<App>` and every page read them from `useViewer()` / `useShellConfig()`
  // instead of the object being threaded down as a prop through 40+ routes.
  const viewerFromShell = viewerFromConfig(shellConfig)
  createRoot(memberAppRoot).render(
    <BrowserRouter>
      <ViewerProvider value={viewerFromShell}>
        <ShellConfigProvider value={shellConfig}>
          <QueryClientProvider client={queryClient}>
            <App />
          </QueryClientProvider>
        </ShellConfigProvider>
      </ViewerProvider>
    </BrowserRouter>,
  )
}

const detailsRootElement = document.getElementById('game-details-react-root')
if (detailsRootElement) {
  createRoot(detailsRootElement).render(
    <GameDetailsApp {...parseGameDetailsRootConfig(detailsRootElement)} />,
  )
}
