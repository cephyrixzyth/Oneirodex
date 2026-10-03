import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test } from 'vitest'

import { railIconPaths } from './railIcons'
import {
  HUB_LINKS,
  INTEGRATION_SECTIONS,
  SETTINGS_GROUPS,
  findSubSection,
  hubIcon,
} from './navConfig'
import { SectionTopNav } from './SectionTopNav'

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SectionTopNav />
    </MemoryRouter>,
  )
}

test('a settings page shows its sub-section children as icon buttons, current one marked', () => {
  at('/admin/scan_match')
  for (const name of ['Server settings', 'Scan / match policy', 'ROM reference sets', 'Quality profiles', 'Storage']) {
    expect(screen.getByRole('link', { name })).toBeInTheDocument()
  }
  expect(screen.getByRole('link', { name: 'Scan / match policy' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  expect(screen.getByRole('link', { name: 'All settings' })).toHaveAttribute(
    'href',
    '/admin/settings',
  )
  // Siblings from other sub-sections stay out of this bar.
  expect(screen.queryByRole('link', { name: 'Themes' })).toBeNull()
})

test('integration tabs sharing one page are told apart by fragment', () => {
  expect(findSubSection('/admin/integrations', '#oidc')?.item.title).toBe('OIDC / SSO')
  expect(findSubSection('/admin/integrations', '#artwork')?.item.title).toBe('Artwork & secondary')
  // The bare overview page owns the path: no sub-section, no buttons.
  expect(findSubSection('/admin/integrations', '')).toBeNull()
  const { container } = at('/admin/integrations')
  expect(container.querySelector('a')).toBeNull()
})

test('pages outside Settings and Integrations get no section bar', () => {
  const { container } = at('/admin/users')
  expect(container.querySelector('a')).toBeNull()
})

test('every destination has exactly one home across Settings and Integrations', () => {
  const seen = new Map<string, string>()
  for (const sub of [...SETTINGS_GROUPS, ...INTEGRATION_SECTIONS]) {
    for (const item of sub.items) {
      expect(seen.get(item.to), `${item.to} listed twice`).toBeUndefined()
      seen.set(item.to, sub.id)
    }
  }
})

test('every icon the admin nav names has a glyph', () => {
  const names = new Set<string>()
  for (const sub of [...SETTINGS_GROUPS, ...INTEGRATION_SECTIONS]) {
    names.add(sub.icon)
    sub.items.forEach((item) => names.add(item.icon))
  }
  for (const links of Object.values(HUB_LINKS)) links.forEach((link) => names.add(hubIcon(link.label)))
  for (const name of names) expect(railIconPaths[name], name).toBeTruthy()
})
