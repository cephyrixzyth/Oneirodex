import { describe, expect, test } from 'vitest'
import { safeExternalUrl } from './safeExternalUrl'

describe('safeExternalUrl', () => {
  test.each([
    ['https://example.com/mod', 'https://example.com/mod'],
    ['  http://example.com/path  ', 'http://example.com/path'],
  ])('keeps absolute HTTP(S) URLs (%s)', (value, expected) => {
    expect(safeExternalUrl(value)).toBe(expected)
  })

  test.each([
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'file:///etc/passwd',
    '//example.com/path',
    '/relative/path',
    'https://user:password@example.com/',
    'https://example.com/\njavascript:alert(1)',
    `https://example.com/${'a'.repeat(2048)}`,
    null,
    42,
  ])('rejects unsafe or non-absolute values (%s)', (value) => {
    expect(safeExternalUrl(value)).toBeNull()
  })
})
