import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { Page } from './Page'

test('shared page names itself in the top bar and keeps a level-one heading for assistive tech', () => {
  const slot = document.createElement('div')
  slot.id = 'od-admin-topbar-title'
  document.body.appendChild(slot)
  try {
    render(
      <Page title="Chat emoji" lede="Household emoji">
        Content
      </Page>,
    )
    expect(screen.getByRole('heading', { name: 'Chat emoji', level: 1 })).toHaveClass(
      'visually-hidden',
    )
    expect(slot).toHaveTextContent('Chat emoji')
    expect(document.title).toBe('Chat emoji · Oneirodex Admin')
  } finally {
    slot.remove()
  }
  const theme = readFileSync(
    resolve(process.cwd(), '../../oneirodex/setup/default_theme/css/od-appbar.css'),
    'utf8',
  )
  expect(theme).toMatch(/:root\[data-chrome='v2'\] \.od-admin-page > h1\s*\{\s*display: block;/)
  expect(theme).not.toMatch(/\.od-admin-page > h1[^{}]*\{\s*display: none;/)
})
