import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OwnershipFilterControls, ownershipFilters } from './OwnershipFilterControls'
import { cleanFilters } from './FilterBar'
import { filtersFromSearchParams, withLibraryParams } from '../libraryQueryParams'

const STORES = [
  { id: 'steam', name: 'Steam' },
  { id: 'gog', name: 'GOG' },
  { id: 'epic', name: 'Epic Games' },
]

test('store_match is sent only when it changes the answer', () => {
  expect(ownershipFilters({ genre: 'RPG' }, [], 'owned', 'all')).toEqual({
    genre: 'RPG',
    ownership: 'owned',
  })
  expect(ownershipFilters({}, ['steam'], 'owned', 'all')).toEqual({
    ownership: 'owned',
    store: 'steam',
  })
  expect(ownershipFilters({}, ['steam', 'gog'], 'owned', 'all')).toEqual({
    ownership: 'owned',
    store: 'steam,gog',
    store_match: 'all',
  })
  expect(ownershipFilters({}, ['steam', 'gog'], 'owned', 'any')).toEqual({
    ownership: 'owned',
    store: 'steam,gog',
  })
  expect(ownershipFilters({ store_match: 'all' }, ['steam', 'gog'], 'unrecorded', 'all')).toEqual({
    ownership: 'unrecorded',
    store: 'steam,gog',
  })
  expect(ownershipFilters({ store: 'steam', ownership: 'owned' }, ['steam'], '', 'any')).toEqual({})
})

function renderControls(filters: Record<string, string>) {
  const onApply = vi.fn()
  render(
    <OwnershipFilterControls
      filters={filters}
      stores={STORES}
      onApply={onApply}
      clean={cleanFilters}
    />,
  )
  return onApply
}

test('owned, then stores, then every-store matching', async () => {
  const user = userEvent.setup()
  let onApply = renderControls({})
  expect(screen.queryByRole('group', { name: 'Stores' })).toBeNull()
  await user.click(screen.getByRole('button', { name: 'Owned' }))
  expect(onApply).toHaveBeenLastCalledWith({ ownership: 'owned' })

  document.body.innerHTML = ''
  onApply = renderControls({ ownership: 'owned', store: 'steam' })
  expect(screen.getByRole('button', { name: 'Steam' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByRole('group', { name: 'Match stores' })).toBeNull()
  await user.click(screen.getByRole('button', { name: 'GOG' }))
  expect(onApply).toHaveBeenLastCalledWith({ ownership: 'owned', store: 'steam,gog' })

  document.body.innerHTML = ''
  onApply = renderControls({ ownership: 'owned', store: 'steam,gog' })
  await user.click(screen.getByRole('button', { name: 'In every selected store' }))
  expect(onApply).toHaveBeenLastCalledWith({
    ownership: 'owned',
    store: 'steam,gog',
    store_match: 'all',
  })
})

test('not recorded is explained as not proof of non-ownership, and All clears everything', async () => {
  const user = userEvent.setup()
  const onApply = renderControls({ ownership: 'unrecorded', store: 'epic', genre: 'RPG' })
  expect(screen.getByText(/Not proof you do not own them/)).toBeInTheDocument()
  expect(screen.queryByRole('group', { name: 'Match stores' })).toBeNull()
  await user.click(screen.getByRole('button', { name: 'All games' }))
  expect(onApply).toHaveBeenLastCalledWith({ genre: 'RPG' })
})

test('the URL round-trips store filters and keeps the filters it carries in step', () => {
  const parsed = filtersFromSearchParams(
    new URLSearchParams('store=steam&store=GOG,epic&store_match=all&ownership=owned&genre=RPG'),
  )
  expect(parsed).toMatchObject({
    store: 'steam,gog,epic',
    store_match: 'all',
    ownership: 'owned',
    genre: 'RPG',
  })
  const next = withLibraryParams(new URLSearchParams('genre=RPG&store=steam&tab=all'), {
    genre: 'RPG',
    ownership: 'unrecorded',
    store: 'gog',
  })
  expect(next.toString()).toBe('genre=RPG&store=gog&tab=all&ownership=unrecorded')
  expect(withLibraryParams(next, { genre: 'RPG' }).toString()).toBe('genre=RPG&tab=all')
  // A changed or cleared filter replaces what the URL held; aliases are rewritten.
  expect(
    withLibraryParams(new URLSearchParams('genre=RPG&q=zelda'), { genre: 'Puzzle' }).toString(),
  ).toBe('genre=Puzzle')
  expect(
    withLibraryParams(new URLSearchParams('genre=RPG&q=zelda'), { name: 'mario' }).toString(),
  ).toBe('name=mario')
  expect(
    withLibraryParams(new URLSearchParams('content_kind=tool&is_vr=1'), {
      item_kind: 'game',
    }).toString(),
  ).toBe('item_kind=game')
  // Filters the URL never carried stay in the cookie only.
  expect(
    withLibraryParams(new URLSearchParams(''), { genre: 'RPG', ownership: 'owned' }).toString(),
  ).toBe('ownership=owned')
})
