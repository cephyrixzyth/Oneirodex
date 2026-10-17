import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import { railIconPaths } from './railIcons'
import {
  HUB_LINKS,
  INTEGRATION_SECTIONS,
  SETTINGS_GROUPS,
  findSubSection,
  hubIcon,
} from './navConfig'
import { SectionTopNav } from './SectionTopNav'
import { resolveAdminPage } from './adminSection'

afterEach(() => {
  vi.restoreAllMocks()
  document.getElementById('od-admin-topbar-slot')?.remove()
})

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SectionTopNav />
    </MemoryRouter>,
  )
}

test('a settings page shows its sub-section children as icon buttons, current one marked', () => {
  at('/admin/scan_match')
  for (const name of [
    'Server settings',
    'Scan / match policy',
    'ROM reference sets',
    'Quality profiles',
    'Storage',
  ]) {
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
  expect(findSubSection('/admin/integrations', '#artwork')?.item.title).toBe('Artwork & secondary')
  expect(findSubSection('/admin/integrations/oidc', '')?.item.title).toBe('OIDC / SSO')
  // The bare overview page owns the path: no sub-section, no buttons.
  expect(findSubSection('/admin/integrations', '')).toBeNull()
  const { container } = at('/admin/integrations')
  expect(container.querySelector('a')).toBeNull()
})

test('pages outside Settings and Integrations get no section bar', () => {
  const { container } = at('/admin/users')
  expect(container.querySelector('a')).toBeNull()
})

test.each([
  ['/scan_management?active_tab=auto', 'Automatic scan'],
  ['/scan_management?active_tab=manual', 'Manual scan'],
  ['/scan_management?active_tab=jobs', 'Scan jobs'],
])('scan view %s has one in-app page switcher with the current view active', (path, active) => {
  at(path)
  const links = screen.getAllByRole('link')
  expect(links.map((link) => link.textContent?.trim())).toEqual([
    'Automatic scan',
    'Manual scan',
    'Scan jobs',
  ])
  expect(screen.getByRole('link', { name: active })).toHaveAttribute('aria-current', 'page')
  expect(links.every((link) => link.getAttribute('href'))).toBe(true)
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
  for (const links of Object.values(HUB_LINKS))
    links.forEach((link) => names.add(hubIcon(link.label)))
  for (const name of names) expect(railIconPaths[name], name).toBeTruthy()
})

test.each(['/admin/chat_emoji', '/admin/features'])('%s has Integration chrome context', (path) => {
  expect(resolveAdminPage(path)).toBe('integrations')
  expect(resolveAdminPage(`${path}/unrelated`)).toBe('generic')
})

test('active destination moves only its portal strip after mount and on resize', async () => {
  const host = document.createElement('div')
  host.id = 'od-admin-topbar-slot'
  document.body.append(host)
  const focus = document.createElement('button')
  document.body.append(focus)
  focus.focus()
  let linkRight = 450
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    return {
      left: this.getAttribute('aria-current') === 'page' ? linkRight - 100 : 0,
      right: this.getAttribute('aria-current') === 'page' ? linkRight : 300,
      top: 0,
      bottom: 30,
      width: 300,
      height: 30,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }
  })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300)
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(600)
  at('/admin/chat_emoji')
  const link = screen.getByRole('link', { name: 'Chat emoji' })
  await waitFor(() => expect(link.closest('.od-cbtn-group')?.scrollLeft).toBe(150))
  expect(host.contains(link)).toBe(true)
  expect(document.activeElement).toBe(focus)
  const strip = link.closest('.od-cbtn-group') as HTMLElement
  linkRight = 80
  fireEvent(window, new Event('resize'))
  expect(strip.scrollLeft).toBe(130)
  expect(strip.scrollTop).toBe(0)
  expect(window.scrollY).toBe(0)
  expect(document.activeElement).toBe(focus)
  focus.remove()
})

test('already visible active link leaves horizontal position unchanged', async () => {
  const host = document.createElement('div')
  host.id = 'od-admin-topbar-slot'
  document.body.append(host)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    right: 200,
    top: 0,
    bottom: 30,
    width: 200,
    height: 30,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300)
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(600)
  at('/admin/features')
  await waitFor(() =>
    expect(
      screen.getByRole('link', { name: 'LiveKit voice' }).closest('.od-cbtn-group'),
    ).not.toBeNull(),
  )
  fireEvent(window, new Event('resize'))
  expect(
    screen.getByRole('link', { name: 'LiveKit voice' }).closest('.od-cbtn-group')?.scrollLeft,
  ).toBe(0)
})
