import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src/pages/DiscoverySectionsPage.css'), 'utf8')

test('opaque modal panel selector outranks the later shared glass panel rule', () => {
  expect(css).toMatch(
    /\.od-discovery-modal \.od-discovery-modal__panel\s*\{\s*background: var\(--od-surface\);/,
  )
})

test('repeated shelf and modal headings use the shared compact type scale', () => {
  expect(css).toMatch(
    /\.od-discovery-shelf-heading,[\s\S]*?h2\s*\{\s*font-size: var\(--od-font-xl\);/,
  )
  expect(css).toMatch(/h3\s*\{\s*font-size: var\(--od-font-lg\);/)
})
