import { safeClaimUrl, safeHttpUrl } from './safeUrl'

test('safeHttpUrl allows http(s) and blocks javascript', () => {
  expect(safeHttpUrl('https://igdb.com/games/1')).toBe('https://igdb.com/games/1')
  expect(safeHttpUrl('http://example.com')).toBe('http://example.com/')
  expect(safeHttpUrl('javascript:alert(1)')).toBeNull()
  expect(safeHttpUrl('')).toBeNull()
})

test('safeClaimUrl keeps http(s) and the store launcher deeplinks, nothing else', () => {
  expect(safeClaimUrl('https://store.steampowered.com/app/1/')).toBe(
    'https://store.steampowered.com/app/1/',
  )
  expect(safeClaimUrl('steam://openurl/https://store.steampowered.com/app/1/')).toBe(
    'steam://openurl/https://store.steampowered.com/app/1/',
  )
  expect(safeClaimUrl('com.epicgames.launcher://store/en-US/p/some-game')).toBe(
    'com.epicgames.launcher://store/en-US/p/some-game',
  )
  const hostile = [
    'javascript:alert(1)',
    '  JavaScript:alert(1)',
    'java\tscript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    'blob:https://example.test/abc',
    'ms-msdt:/id PCWDiagnostic',
    '',
    null,
    undefined,
    42,
  ]
  for (const url of hostile) {
    expect(safeClaimUrl(url)).toBeNull()
  }
})
