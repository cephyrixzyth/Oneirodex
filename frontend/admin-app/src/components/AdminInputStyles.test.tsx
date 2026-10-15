import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8')
const scoped = css.match(/\.od-admin-page \.od-admin-input:not\(:where\([^)]*\)\)/)?.[0] || ''

test.each(['text', 'url', 'number', 'password', 'email', 'search', 'date', 'tel', 'time', 'file'])(
  'explicit %s fields use the scoped admin box',
  (type) => {
    const page = document.createElement('div')
    page.className = 'od-admin-page'
    const form = document.createElement('form')
    page.append(form)
    const input = document.createElement('input')
    input.type = type
    input.className = 'od-admin-input'
    form.append(input)
    expect(scoped).toContain('.od-admin-page .od-admin-input')
    expect(input.matches(scoped)).toBe(true)
    input.className = 'specialized-control'
    expect(input.matches(scoped)).toBe(false)
  },
)

test.each(['select', 'textarea'])('%s shares the explicit field box', (tag) => {
  const page = document.createElement('div')
  page.className = 'od-admin-page'
  const input = document.createElement(tag)
  input.className = 'od-admin-input'
  page.append(input)
  expect(input.matches(scoped)).toBe(true)
})

test.each(['range', 'color', 'checkbox', 'radio'])(
  '%s retains its native control styling',
  (type) => {
    const page = document.createElement('div')
    page.className = 'od-admin-page'
    const input = document.createElement('input')
    input.type = type
    input.className = 'od-admin-input'
    page.append(input)
    expect(input.matches(scoped)).toBe(false)
  },
)

test('shared box and focus rules use tokens and do not replace native appearance', () => {
  const box = css.match(/\.od-admin-input,[\s\S]*?\n\}/)?.[0] || ''
  expect(box).toContain('background: var(--od-surface-2)')
  expect(box).toContain('border: 1px solid var(--od-border)')
  expect(box).toContain('color: var(--od-text)')
  expect(box).toContain('font: inherit')
  expect(box).toContain('.od-admin-panel .od-admin-input')
  const focus = css.match(/\.od-admin-page \.od-admin-input[^{}]*:focus,[\s\S]*?\n\}/)?.[0] || ''
  const visible =
    css.match(/\.od-admin-page \.od-admin-input[^{}]*:focus-visible,[\s\S]*?\n\}/)?.[0] || ''
  expect(focus).toContain('background: var(--od-surface-2)')
  expect(visible).toContain('outline: 2px solid var(--od-focus-ring, var(--od-accent))')
  expect(visible).toContain('outline-offset: 2px')
  expect(`${box}${focus}${visible}`).not.toMatch(/appearance\s*:/)
})
