import { describe, expect, it } from 'vitest'

import {
  assertValidGameUuid,
  buildDownloadStreamPath,
  buildInitiateDownloadPath,
  buildLocalArchiveName,
  buildLocalInstallDirName,
  isValidGameUuid,
  joinUrl,
} from './paths.js'

describe('path helpers', () => {
  it('joins base URL and path without duplicate slashes', () => {
    expect(joinUrl('https://example.com/', '/api/collections')).toBe(
      'https://example.com/api/collections',
    )

    expect(joinUrl('https://example.com', 'download_zip/5')).toBe(
      'https://example.com/download_zip/5',
    )
  })

  it('builds initiate and stream paths used by the desktop pipeline', () => {
    const uuid = '11111111-1111-1111-1111-111111111111'

    expect(buildInitiateDownloadPath(uuid)).toBe(`/api/downloads/games/${uuid}`)

    expect(buildDownloadStreamPath(42)).toBe('/download_zip/42')
  })

  it('builds local archive and install directory names', () => {
    const uuid = 'game-42'

    expect(buildLocalArchiveName(uuid)).toBe('game-42.zip')

    expect(buildLocalInstallDirName(uuid)).toBe('game-42')
  })

  it('builds isolated update-generation names from a valid id and generation', () => {
    const generation = 'update-11111111-1111-1111-1111-111111111111'

    expect(buildLocalInstallDirName('game-42', generation)).toBe(`game-42-${generation}`)
    expect(buildLocalArchiveName('game-42', generation)).toBe(`game-42-${generation}.zip`)
  })
})

describe('game uuid as a path segment', () => {
  const hostile = [
    '.',
    '..',
    '',
    ' ',
    '../x',
    '..\\x',
    'a/b',
    'a\\b',
    '/abs',
    'C:\\Windows',
    '\\\\host\\share',
    'game 1',
    'game.1',
    'game\u0000',
    'game\n',
    'a'.repeat(65),
  ]

  it('accepts server uuids and plain slugs', () => {
    for (const ok of [
      '11111111-1111-1111-1111-111111111111',
      'game-42',
      'GAME_42',
      'a',
      'a'.repeat(64),
    ]) {
      expect(isValidGameUuid(ok), ok).toBe(true)
      expect(assertValidGameUuid(ok)).toBe(ok)
    }
  })

  it('rejects ids that are not a single plain segment', () => {
    for (const bad of hostile) {
      expect(isValidGameUuid(bad), JSON.stringify(bad)).toBe(false)
      expect(() => assertValidGameUuid(bad), JSON.stringify(bad)).toThrow(/Invalid game id/)
    }
    expect(isValidGameUuid(undefined)).toBe(false)
    expect(isValidGameUuid(42)).toBe(false)
  })

  it('refuses to build any local path or URL from a hostile id', () => {
    // "." would make `installs/.` the installs root itself - the directory the
    // extract step wipes before unpacking.
    for (const bad of hostile) {
      expect(() => buildLocalInstallDirName(bad), JSON.stringify(bad)).toThrow(/Invalid game id/)
      expect(() => buildLocalArchiveName(bad), JSON.stringify(bad)).toThrow(/Invalid game id/)
      expect(() => buildInitiateDownloadPath(bad), JSON.stringify(bad)).toThrow(/Invalid game id/)
    }
  })

  it('refuses a hostile update generation', () => {
    for (const bad of ['..', '../x', 'a/b', 'a\\b', 'x'.repeat(81)]) {
      expect(() => buildLocalInstallDirName('game-42', bad), bad).toThrow(
        /Invalid update generation/,
      )
      expect(() => buildLocalArchiveName('game-42', bad), bad).toThrow(/Invalid update generation/)
    }
  })
})
