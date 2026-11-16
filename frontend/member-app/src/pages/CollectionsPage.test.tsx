import { vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { CollectionDetailPage } from './CollectionDetailPage'
import { CollectionsPage } from './CollectionsPage'
import * as collectionsApi from '../api/collections'
import { ShellHarness } from '../testShell'

vi.mock('../api/collections', () => ({
  fetchCollections: vi.fn(),
  fetchCollection: vi.fn(),
  createCollection: vi.fn(),
  updateCollection: vi.fn(),
  deleteCollection: vi.fn(),
  reorderCollectionItems: vi.fn(),
  addCollectionItem: vi.fn(),
  removeCollectionItem: vi.fn(),
  searchGames: vi.fn(),
}))

function renderPage() {
  return render(
    <MemoryRouter>
      <ShellHarness>
        <CollectionsPage />
      </ShellHarness>
    </MemoryRouter>,
  )
}

function renderDetailPage(uuid = 'abc-123', shellConfig = {}) {
  return render(
    <MemoryRouter initialEntries={[`/collections/${uuid}`]}>
      <Routes>
        <Route
          path="/collections/:collectionUuid"
          element={
            <ShellHarness shell={shellConfig}>
              <CollectionDetailPage />
            </ShellHarness>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(collectionsApi.fetchCollections).mockReset()
  vi.mocked(collectionsApi.fetchCollection).mockReset()
  vi.mocked(collectionsApi.createCollection).mockReset()
  vi.mocked(collectionsApi.updateCollection).mockReset()
  vi.mocked(collectionsApi.deleteCollection).mockReset()
  vi.mocked(collectionsApi.reorderCollectionItems).mockReset()
  vi.mocked(collectionsApi.addCollectionItem).mockReset()
  vi.mocked(collectionsApi.removeCollectionItem).mockReset()
  vi.mocked(collectionsApi.searchGames).mockReset()
  vi.mocked(collectionsApi.searchGames).mockResolvedValue([])
})

test('lists collections from API and links to detail routes', async () => {
  vi.mocked(collectionsApi.fetchCollections).mockResolvedValue({
    collections: [
      {
        id: 1,
        uuid: 'abc-123',
        name: 'Cozy co-op nights',
        description: 'Couch games',
        is_public: true,
        is_system: false,
        item_count: 3,
        can_edit: true,
      },
    ],
  })

  renderPage()

  expect(screen.getByRole('status', { busy: true })).toBeInTheDocument()

  const link = await screen.findByRole('link', { name: /Cozy co-op nights/ })
  expect(link).toHaveAttribute('href', '/collections/abc-123')
  expect(within(link).getByText('Couch games')).toBeInTheDocument()
  expect(within(link).getByText(/Public/)).toBeInTheDocument()
  expect(within(link).getByText(/3 games/)).toBeInTheDocument()
})

test('shows empty state when no collections', async () => {
  vi.mocked(collectionsApi.fetchCollections).mockResolvedValue({ collections: [] })

  renderPage()

  expect(
    await screen.findByText('No collections yet. Create your first shelf with the form above.'),
  ).toBeInTheDocument()
})

test('shows retry control when the request fails', async () => {
  vi.mocked(collectionsApi.fetchCollections).mockRejectedValueOnce(new Error('collections 500'))
  vi.mocked(collectionsApi.fetchCollections).mockResolvedValueOnce({ collections: [] })

  renderPage()

  expect(await screen.findByText('Unable to load collections.')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /Try again/i }))

  expect(
    await screen.findByText('No collections yet. Create your first shelf with the form above.'),
  ).toBeInTheDocument()
})

test('creates a collection and shows it in the list', async () => {
  vi.mocked(collectionsApi.fetchCollections).mockResolvedValue({ collections: [] })
  vi.mocked(collectionsApi.createCollection).mockResolvedValue({
    id: 7,
    uuid: 'new-uuid',
    name: 'Roguelites',
    description: '',
    is_public: true,
    is_system: false,
    item_count: 0,
    can_edit: true,
  })

  renderPage()

  await screen.findByText('No collections yet. Create your first shelf with the form above.')

  await userEvent.type(screen.getByLabelText('Name'), 'Roguelites')
  await userEvent.click(screen.getByRole('button', { name: 'Create shelf' }))

  expect(collectionsApi.createCollection).toHaveBeenCalledWith({
    name: 'Roguelites',
    description: '',
    isPublic: true,
  })
  expect(await screen.findByRole('link', { name: /Roguelites/ })).toHaveAttribute(
    'href',
    '/collections/new-uuid',
  )
})

test('explains when a whitespace-only collection name is submitted', async () => {
  vi.mocked(collectionsApi.fetchCollections).mockResolvedValue({ collections: [] })

  renderPage()

  await screen.findByText('No collections yet. Create your first shelf with the form above.')
  await userEvent.type(screen.getByLabelText('Name'), '   ')
  await userEvent.click(screen.getByRole('button', { name: 'Create shelf' }))

  expect(collectionsApi.createCollection).not.toHaveBeenCalled()
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Enter a shelf name before creating it.',
  )
})

test('detail page renders items for the routed collection uuid', async () => {
  vi.mocked(collectionsApi.fetchCollection).mockResolvedValue({
    id: 1,
    uuid: 'abc-123',
    name: 'Cozy co-op nights',
    description: 'Couch games',
    is_public: true,
    is_system: false,
    can_edit: true,
    items: [{ id: 5, game_uuid: 'game-1', game_name: 'Overcooked', position: 0 }],
  })

  renderDetailPage()

  expect(screen.getByRole('status', { busy: true })).toBeInTheDocument()
  expect(await screen.findByRole('heading', { name: 'Cozy co-op nights' })).toBeInTheDocument()
  expect(collectionsApi.fetchCollection).toHaveBeenCalledWith(
    'abc-123',
    expect.objectContaining({ signal: expect.anything() }),
  )
  expect(screen.getByRole('link', { name: /Overcooked/ })).toHaveAttribute(
    'href',
    '/game_details/game-1',
  )
  expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  expect(screen.getByLabelText('Name')).toHaveValue('Cozy co-op nights')
})

test('detail page saves collection edits', async () => {
  vi.mocked(collectionsApi.fetchCollection).mockResolvedValue({
    id: 1,
    uuid: 'abc-123',
    name: 'Cozy',
    description: 'Old blurb',
    is_public: true,
    is_system: false,
    can_edit: true,
    items: [],
  })
  vi.mocked(collectionsApi.updateCollection).mockResolvedValue({
    id: 1,
    uuid: 'abc-123',
    name: 'Cozy remixed',
    description: 'New blurb',
    is_public: false,
    is_system: false,
    can_edit: true,
    item_count: 0,
    items: [],
  })

  renderDetailPage()
  await screen.findByRole('heading', { name: 'Cozy' })

  const nameInput = screen.getByLabelText('Name')
  await userEvent.clear(nameInput)
  await userEvent.type(nameInput, 'Cozy remixed')
  const descriptionInput = screen.getByLabelText('Description')
  await userEvent.clear(descriptionInput)
  await userEvent.type(descriptionInput, 'New blurb')
  await userEvent.click(screen.getByLabelText('Public'))
  await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

  expect(collectionsApi.updateCollection).toHaveBeenCalledWith('abc-123', {
    name: 'Cozy remixed',
    description: 'New blurb',
    isPublic: false,
  })
  expect(await screen.findByRole('heading', { name: 'Cozy remixed' })).toBeInTheDocument()
})

test('detail page reorders items with up/down controls', async () => {
  vi.mocked(collectionsApi.fetchCollection).mockResolvedValue({
    id: 1,
    uuid: 'abc-123',
    name: 'Shelf',
    is_public: true,
    is_system: false,
    can_edit: true,
    items: [
      { id: 1, game_uuid: 'game-a', game_name: 'Alpha', position: 0 },
      { id: 2, game_uuid: 'game-b', game_name: 'Beta', position: 1 },
    ],
  })
  vi.mocked(collectionsApi.reorderCollectionItems).mockResolvedValue({
    id: 1,
    uuid: 'abc-123',
    name: 'Shelf',
    is_public: true,
    is_system: false,
    can_edit: true,
    item_count: 2,
    items: [
      { id: 2, game_uuid: 'game-b', game_name: 'Beta', position: 0 },
      { id: 1, game_uuid: 'game-a', game_name: 'Alpha', position: 1 },
    ],
  })

  renderDetailPage()
  await screen.findByRole('heading', { name: 'Shelf' })

  await userEvent.click(screen.getByRole('button', { name: 'Move Alpha down' }))

  expect(collectionsApi.reorderCollectionItems).toHaveBeenCalledWith('abc-123', [
    'game-b',
    'game-a',
  ])
})

test('detail page shows an empty state when the collection has no games', async () => {
  vi.mocked(collectionsApi.fetchCollection).mockResolvedValue({
    id: 2,
    uuid: 'empty-uuid',
    name: 'Empty shelf',
    description: null,
    is_public: true,
    is_system: false,
    can_edit: true,
    items: [],
  })

  renderDetailPage('empty-uuid')

  expect(
    await screen.findByText('No games in this collection yet. Search below to add one.'),
  ).toBeInTheDocument()
  expect(screen.getByLabelText('Search games')).toBeInTheDocument()
})

test('detail page searches and adds a picked game', async () => {
  vi.mocked(collectionsApi.fetchCollection).mockResolvedValue({
    id: 1,
    uuid: 'abc-123',
    name: 'Cozy',
    is_public: true,
    is_system: false,
    can_edit: true,
    items: [],
  })
  vi.mocked(collectionsApi.searchGames).mockResolvedValue([
    { id: 9, uuid: 'game-9', name: 'Celeste' },
  ])
  vi.mocked(collectionsApi.addCollectionItem).mockResolvedValue({
    id: 11,
    game_uuid: 'game-9',
    game_name: 'Celeste',
    position: 0,
  })

  renderDetailPage()
  await screen.findByRole('heading', { name: 'Cozy' })

  await userEvent.type(screen.getByLabelText('Search games'), 'Cel')
  const addButton = await screen.findByRole('button', { name: /Celeste/ })
  await userEvent.click(addButton)

  expect(collectionsApi.addCollectionItem).toHaveBeenCalledWith('abc-123', 'game-9')
  expect(await screen.findByRole('link', { name: /Celeste/ })).toBeInTheDocument()
})

test('new chrome puts the create form behind one button', async () => {
  // An always-visible three-field form above the list is the noise bar two
  // exists to absorb; creating a shelf is an action, not page furniture.
  const user = userEvent.setup()
  vi.mocked(collectionsApi.fetchCollections).mockResolvedValue({ collections: [] })

  render(
    <MemoryRouter>
      <ShellHarness shell={{ enableNewChrome: true }}>
        <CollectionsPage />
      </ShellHarness>
    </MemoryRouter>,
  )
  await screen.findByText(/No collections yet/)

  expect(screen.queryByRole('heading', { name: 'Collections' })).toBeNull()
  expect(screen.queryByPlaceholderText('Cozy co-op nights')).toBeNull()

  const newShelf = screen.getByRole('button', { name: /New shelf/ })
  expect(newShelf.className).not.toContain('od-cbtn--primary')
  expect(newShelf.querySelector('svg')).toBeNull()
  await user.click(newShelf)
  expect(screen.getByPlaceholderText('Cozy co-op nights')).toBeInTheDocument()
})

test('the empty state points at the control that actually exists', async () => {
  // It used to say "with the form above", which is wrong once the form is
  // behind a button — and that sentence is the only guidance a new user gets.
  vi.mocked(collectionsApi.fetchCollections).mockResolvedValue({ collections: [] })
  render(
    <MemoryRouter>
      <ShellHarness shell={{ enableNewChrome: true }}>
        <CollectionsPage />
      </ShellHarness>
    </MemoryRouter>,
  )
  expect(await screen.findByText(/from New shelf above/)).toBeInTheDocument()
})

test('new chrome still says which collection you are looking at', async () => {
  // Regression: the v2 retirement rule matches `.od-page-header > h1`, and on
  // this page that h1 is the *collection's name*. Before the move, the page
  // rendered under the new chrome with nothing identifying it at all.
  vi.mocked(collectionsApi.fetchCollection).mockResolvedValue({
    id: 1,
    uuid: 'abc-123',
    name: 'Cozy co-op nights',
    description: 'Couch games',
    is_public: true,
    is_system: false,
    can_edit: true,
    items: [],
  })

  renderDetailPage('abc-123', { enableNewChrome: true })

  expect(await screen.findByText('Cozy co-op nights')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Delete collection' })).toBeInTheDocument()
})

test('a collection you cannot edit offers no delete button', async () => {
  vi.mocked(collectionsApi.fetchCollection).mockResolvedValue({
    id: 2,
    uuid: 'sys-1',
    name: 'Recently added',
    is_system: true,
    can_edit: false,
    items: [],
  })

  renderDetailPage('sys-1', { enableNewChrome: true })

  expect(await screen.findByText('Recently added')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete collection' })).toBeNull()
})
