import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { Page } from './Page'

test('shared page retains its title as an actual visible level-one heading', () => {
  render(
    <Page title="Chat emoji" lede="Household emoji">
      Content
    </Page>,
  )
  expect(screen.getByRole('heading', { name: 'Chat emoji', level: 1 })).toBeVisible()
  const theme = readFileSync(
    resolve(process.cwd(), '../../oneirodex/setup/default_theme/css/od-appbar.css'),
    'utf8',
  )
  expect(theme).toMatch(/:root\[data-chrome='v2'\] \.od-admin-page > h1\s*\{\s*display: block;/)
  expect(theme).not.toMatch(/\.od-admin-page > h1[^{}]*\{\s*display: none;/)
})
