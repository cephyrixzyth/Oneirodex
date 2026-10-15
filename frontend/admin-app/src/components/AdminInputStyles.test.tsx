import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8').replace(/\s+/g, ' ')
const box = css.match(/\.od-admin-input,.*?\{[^}]*\}/)?.[0] || ''

test.each(['text', 'url', 'number', 'password', 'email', 'search', 'date', 'tel', 'time', 'file'])(
  'explicit %s fields use the shared admin box',
  () => {
    expect(box).toContain('.od-admin-input')
    expect(box).toContain('.od-admin-page .od-admin-input:not(:where(')
    expect(box).toContain('.od-admin-panel .od-admin-input:not(:where(')
  },
)

test.each(['select', 'textarea'])('%s gets the shared box when unclassed', (tag) => {
  expect(box).toContain(`.od-admin-panel ${tag}:not([class])`)
  expect(box).toContain(`.od-admin-page ${tag}:not([class])`)
})

test.each(['range', 'color', 'checkbox', 'radio'])(
  '%s retains its native control styling',
  (type) => {
    expect(box).toContain(`[type='${type}']`)
  },
)

test('shared box and focus rules use theme tokens without replacing native appearance', () => {
  expect(box).toContain('background: var(--od-surface-2)')
  expect(box).toContain('border: 1px solid var(--od-border)')
  expect(box).toContain('color: var(--od-text)')
  expect(box).toContain('font: inherit')

  const focus = css.match(/\.od-admin-page[^{}]*:focus,.*?\{[^}]*\}/)?.[0] || ''
  const visible = css.match(/\.od-admin-page[^{}]*:focus-visible,.*?\{[^}]*\}/)?.[0] || ''
  expect(focus).toContain('background: var(--od-surface-2)')
  expect(visible).toContain('outline: 2px solid var(--od-focus-ring, var(--od-accent))')
  expect(visible).toContain('outline-offset: 2px')
  expect(`${box}${focus}${visible}`).not.toMatch(/appearance\s*:/)
})
