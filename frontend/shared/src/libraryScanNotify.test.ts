import { beforeEach, expect, test } from 'vitest'
import {
  isLibraryGamesAddedNotification,
  libraryGamesAddedToastMessage,
  markLibraryScanToastSeen,
  pickUnseenLibraryScanToasts,
  wasLibraryScanToastSeen,
} from './libraryScanNotify'

beforeEach(() => {
  sessionStorage.clear()
})

test('isLibraryGamesAddedNotification matches kind and title patterns', () => {
  expect(isLibraryGamesAddedNotification({ kind: 'library_games_added' })).toBe(true)
  expect(
    isLibraryGamesAddedNotification({
      title: '3 games added to Library Retro',
      body: 'Incremental watch',
    }),
  ).toBe(true)
  expect(isLibraryGamesAddedNotification({ title: 'Friend request' })).toBe(false)
  expect(isLibraryGamesAddedNotification(null)).toBe(false)
})

test('pickUnseenLibraryScanToasts skips seen ids and soft-caps', () => {
  markLibraryScanToastSeen(1)
  const picked = pickUnseenLibraryScanToasts(
    [
      { id: 1, kind: 'library_games_added', title: '1 games added to Library A' },
      { id: 2, title: '2 games added to Library B' },
      { id: 3, title: 'Friend request' },
      { id: 4, type: 'games_added', title: '4 games added to Library C' },
    ],
    { limit: 2 },
  )
  expect(picked.map((r) => r.id)).toEqual([2, 4])
  expect(wasLibraryScanToastSeen(1)).toBe(true)
  expect(libraryGamesAddedToastMessage(picked[0])).toMatch(/Library B/)
})

test('pickUnseenLibraryScanToasts soft-fails on empty input', () => {
  expect(pickUnseenLibraryScanToasts(undefined)).toEqual([])
  expect(pickUnseenLibraryScanToasts([])).toEqual([])
})
