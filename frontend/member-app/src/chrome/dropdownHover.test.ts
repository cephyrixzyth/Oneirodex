/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from 'vitest'

const HERE = dirname(fileURLToPath(import.meta.url))
const CSS = readFileSync(join(HERE, 'TopNav.css'), 'utf8')

test('top-nav dropdown hover and focus use a solid readable surface', () => {
  const surfaceHighlights = CSS.match(
    /background:\s*color-mix\(in srgb, var\(--od-accent\) 30%, var\(--od-surface-2\)\);/g,
  )

  expect(surfaceHighlights).toHaveLength(2)
  expect(CSS).not.toContain('16%, transparent')
  expect(CSS.match(/color:\s*var\(--od-text\);/g)?.length).toBeGreaterThanOrEqual(2)
})
