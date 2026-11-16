import {
  parseDiscoverRootConfig,
  parseFavoritesRootConfig,
  parseRootConfig,
  parseShellConfig,
} from './main'

test('parses Library template data attributes', () => {
  const root = document.createElement('div')
  root.dataset.perPage = '50'
  root.dataset.defaultSort = 'rating'
  root.dataset.defaultSortOrder = 'desc'
  root.dataset.isAdmin = 'true'
  root.dataset.showPlayStatus = 'false'
  root.dataset.libraryCount = '2'
  root.dataset.gamesCount = '12'
  root.dataset.enableDeleteOnDisk = 'true'
  root.dataset.scanHasRun = '1'
  root.dataset.unmatchedCount = '7'
  root.dataset.currentFilters = '{"genre":"Action"}'

  expect(parseRootConfig(root)).toEqual({
    perPage: 50,
    defaultSort: 'rating',
    defaultSortOrder: 'desc',
    isAdmin: true,
    showPlayStatus: false,
    libraryCount: 2,
    gamesCount: 12,
    enableDeleteOnDisk: true,
    scanHasRun: true,
    unmatchedCount: 7,
    locale: 'en',
    currentFilters: { genre: 'Action' },
  })
})

/* The absent case is the one that ships on every page except /library: only
   the library route supplies these, so every other shell renders the shelf
   without them. They must read as "no scan yet" rather than as undefined,
   which would take the empty state down the "a scan ran" branch on a fresh
   install (UID-043). */
test('first-run attributes default to not-yet-scanned when absent', () => {
  const root = document.createElement('div')
  root.dataset.libraryCount = '1'
  root.dataset.gamesCount = '0'

  const config = parseRootConfig(root)
  expect(config.scanHasRun).toBe(false)
  expect(config.unmatchedCount).toBe(0)
})

test('parses Favorites template data attributes', () => {
  const root = document.createElement('div')
  root.dataset.isAdmin = 'false'
  root.dataset.showPlayStatus = 'true'

  expect(parseFavoritesRootConfig(root)).toEqual({
    isAdmin: false,
    showPlayStatus: true,
  })
})

test('parses Discover template data attributes', () => {
  const root = document.createElement('div')
  root.dataset.isAdmin = 'true'

  expect(parseDiscoverRootConfig(root)).toEqual({
    isAdmin: true,
  })
})

test('parses Discover admin=false', () => {
  const root = document.createElement('div')
  root.dataset.isAdmin = 'false'

  expect(parseDiscoverRootConfig(root)).toEqual({
    isAdmin: false,
  })
})

test('parses SPA shell config including tileSize', () => {
  const root = document.createElement('div')
  root.dataset.tileSize = 'XL'
  root.dataset.isAdmin = 'true'
  root.dataset.perPage = '50'
  root.dataset.defaultSort = 'name'
  root.dataset.defaultSortOrder = 'asc'
  root.dataset.username = 'ada'
  root.dataset.userId = '42'
  root.dataset.currentFilters = '{}'

  const config = parseShellConfig(root)
  expect(config.tileSize).toBe('XL')
  expect(config.isAdmin).toBe(true)
  expect(config.perPage).toBe(50)
  expect(config.username).toBe('ada')
  expect(config.userId).toBe(42)
  expect(config.sections).toBeUndefined()
})

test('uses the legacy page-size default when the shell omits perPage', () => {
  const root = document.createElement('div')

  expect(parseShellConfig(root).perPage).toBe(50)
})
