import { describe, expect, it } from 'vitest'

import {
  addedCountOf,
  burstToastMessages,
  groupLibraryScanToasts,
  groupedToastMessage,
  libraryKeyOf,
} from './libraryScanNotify'

/**
 * One toast per library, not per increment (GT-B11).
 *
 * A scan emits a notification each time it adds games, so a single library
 * produced a stream of near-identical toasts — "3 games added", "2 games
 * added", "5 games added" — which is noise standing in for one useful fact.
 */

describe('libraryKeyOf', () => {
  it('prefers explicit fields', () => {
    expect(libraryKeyOf({ library: 'Retro' })).toBe('Retro')
    expect(libraryKeyOf({ library_name: 'PC' })).toBe('PC')
    expect(libraryKeyOf({ data: { library: 'Nested' } })).toBe('Nested')
  })

  it('falls back to parsing the message', () => {
    expect(libraryKeyOf({ title: '4 games added to library Switch' })).toBe('Switch')
  })

  it('keeps unattributable rows separate', () => {
    // Merging rows we cannot attribute would under-report: two unrelated
    // libraries would collapse into one toast with a summed count.
    const a = libraryKeyOf({ id: 1, title: 'something else' })
    const b = libraryKeyOf({ id: 2, title: 'something else' })
    expect(a).not.toBe(b)
  })
})

describe('addedCountOf', () => {
  it('reads an explicit count', () => {
    expect(addedCountOf({ count: 7 })).toBe(7)
  })

  it('parses a count out of the message', () => {
    expect(addedCountOf({ title: '12 games added to library PC' })).toBe(12)
  })

  it('treats an unknown count as one rather than zero', () => {
    // Zero would make a real batch sum to "0 games added".
    expect(addedCountOf({ title: 'games added' })).toBe(1)
  })
})

describe('groupLibraryScanToasts', () => {
  it('collapses a burst for one library into a single summed entry', () => {
    const groups = groupLibraryScanToasts([
      { id: 1, library: 'Retro', count: 3 },
      { id: 2, library: 'Retro', count: 2 },
      { id: 3, library: 'Retro', count: 5 },
    ])

    expect(groups).toHaveLength(1)
    expect(groups[0].total).toBe(10)
    expect(groups[0].rows).toHaveLength(3)
    expect(groupedToastMessage(groups[0])).toBe('10 games added to Retro')
  })

  it('keeps separate libraries separate', () => {
    const groups = groupLibraryScanToasts([
      { id: 1, library: 'Retro', count: 3 },
      { id: 2, library: 'PC', count: 4 },
    ])

    expect(groups).toHaveLength(2)
    expect(groups.map((g) => g.total).sort()).toEqual([3, 4])
  })

  it('leaves a lone notification with its original wording', () => {
    // A single add should read exactly as the backend phrased it; the summary
    // form is only worth having when it is replacing several toasts.
    const groups = groupLibraryScanToasts([
      { id: 1, library: 'Retro', title: '3 games added to library Retro' },
    ])

    expect(groupedToastMessage(groups[0])).toBe('3 games added to library Retro')
  })

  it('marks every row in a group, so a batch cannot re-toast', () => {
    const groups = groupLibraryScanToasts([
      { id: 1, library: 'Retro', count: 1 },
      { id: 2, library: 'Retro', count: 1 },
    ])

    // The hook marks group.rows — if grouping dropped rows, the unmarked ones
    // would toast again on the next poll.
    expect(groups[0].rows.map((r) => r.id)).toEqual([1, 2])
  })
})

describe('burstToastMessages', () => {
  it('keeps three libraries as named toasts', () => {
    const groups = groupLibraryScanToasts(
      ['A', 'B', 'C'].map((library, i) => ({
        id: i + 1,
        library,
        count: 1,
      })),
    )
    const burst = burstToastMessages(groups)
    expect(burst).toHaveLength(3)
    expect(burst.every((item) => item.count === 1)).toBe(true)
  })

  it('collapses four libraries into one count', () => {
    const groups = groupLibraryScanToasts(
      ['A', 'B', 'C', 'D'].map((library, i) => ({
        id: i + 1,
        library,
        count: 2,
      })),
    )
    const burst = burstToastMessages(groups)
    expect(burst).toHaveLength(1)
    expect(burst[0].message).toBe('4 notifications')
    expect(burst[0].count).toBe(4)
    expect(burst[0].rows).toHaveLength(4)
  })

  it('collapses a three-library burst at the narrow viewport cap', () => {
    const groups = groupLibraryScanToasts(
      ['A', 'B', 'C'].map((library, i) => ({
        id: i + 1,
        library,
        count: 1,
      })),
    )
    const burst = burstToastMessages(groups, { maxIndividual: 2 })
    expect(burst).toHaveLength(1)
    expect(burst[0].message).toBe('3 notifications')
    expect(burst[0].rows).toHaveLength(3)
  })
})
