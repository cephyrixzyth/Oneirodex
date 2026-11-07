import { afterEach, expect, test } from 'vitest'
import {
  RECENT_TITLES_KEY,
  clearLegacyRecentTitles,
  mergeSuggestRecent,
  normalizeRecentTitle,
} from './recentTitles'

afterEach(() => {
  window.localStorage.removeItem(RECENT_TITLES_KEY)
})

test('normalizeRecentTitle drops empty rows', () => {
  expect(normalizeRecentTitle({ uuid: '', name: 'X' })).toBeNull()
  expect(normalizeRecentTitle({ uuid: 'a', name: '  ' })).toBeNull()
  expect(normalizeRecentTitle({ uuid: 'a', name: 'Hades' })).toEqual({
    uuid: 'a',
    name: 'Hades',
    hint: 'Opened here',
  })
})

test('legacy origin-global history is removed', () => {
  window.localStorage.setItem(
    RECENT_TITLES_KEY,
    JSON.stringify([{ uuid: 'restricted', name: 'Private title' }]),
  )

  clearLegacyRecentTitles()

  expect(window.localStorage.getItem(RECENT_TITLES_KEY)).toBeNull()
})

test('recent suggestions use only current server rows', () => {
  const merged = mergeSuggestRecent([
    { uuid: 'p', name: 'Played', hint: 'Played recently' },
    { uuid: 'p', name: 'Duplicate' },
    { uuid: '', name: 'Invalid' },
  ])

  expect(merged).toEqual([{ uuid: 'p', name: 'Played', hint: 'Played recently', cover_url: null }])
})
