/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from 'vitest'

const HERE = dirname(fileURLToPath(import.meta.url))
const CSS = readFileSync(join(HERE, 'TopNav.css'), 'utf8')
const LEGACY_THEME_CSS = readFileSync(
  join(HERE, '../../../../oneirodex/setup/default_theme/css/base.css'),
  'utf8',
)

test('top-nav dropdown hover and focus use a solid readable surface', () => {
  const surfaceHighlights = CSS.match(
    /background:\s*color-mix\(in srgb, var\(--od-accent\) 30%, var\(--od-surface-2\)\);/g,
  )

  expect(surfaceHighlights).toHaveLength(2)
  expect(CSS).not.toContain('16%, transparent')
  expect(CSS.match(/color:\s*var\(--od-text\);/g)?.length).toBeGreaterThanOrEqual(2)
  expect(LEGACY_THEME_CSS).toContain('.popup-menu .menu-button:focus-visible')
  expect(LEGACY_THEME_CSS).toContain('.menu-item > a:focus-visible')
  expect(LEGACY_THEME_CSS).toContain('background-color: color-mix(in srgb, var(--od-accent) 30%, var(--od-surface))')
  expect(LEGACY_THEME_CSS).not.toContain('var(--od-accent) 20%, transparent')
})
