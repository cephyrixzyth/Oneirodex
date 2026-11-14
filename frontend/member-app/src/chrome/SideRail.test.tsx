import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, test, vi } from 'vitest'

import { SideRail } from './SideRail'
import { railIconPaths } from './railIcons'
import { getMoreGroups, getMoreLinks, getPrimaryLinks } from './navConfig'
import { ShellHarness } from '../testShell'

const sideRailCss = readFileSync(resolve(process.cwd(), 'src/chrome/SideRail.css'), 'utf8')

/**
 * The rail's whole justification is that nothing is hidden (GT-B2).
 *
 * The old top bar held five destinations and pushed eighteen into a "More"
 * dropdown; the rail exists to make all twenty-three reachable in one place. If
 * a destination stops appearing here, the redesign has silently regressed to
 * the thing it replaced — so completeness is asserted against navConfig rather
 * than against a hand-written list that could drift with it.
 */

function renderRail({
  shell = {},
  ...props
}: { shell?: Record<string, unknown>; [key: string]: unknown } = {}) {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <ShellHarness shell={{ showTrailers: true, showHelp: true, enableVr: true, ...shell }}>
        <SideRail {...props} />
      </ShellHarness>
    </MemoryRouter>,
  )
}

test('every primary destination is present', () => {
  const { container } = renderRail()

  for (const link of getPrimaryLinks()) {
    expect(container.querySelector(`a[href="${link.to}"]`)).toBeTruthy()
  }
})

test('every former More-menu destination is present, ungated by an overflow', () => {
  const { container } = renderRail()
  const groups = getMoreGroups({ showTrailers: true, showHelp: true, enableVr: true })

  expect(groups.length).toBeGreaterThan(0)
  for (const group of groups) {
    for (const link of group.links) {
      if (link!.action) {
        // Panel openers are buttons, not links, but still must be offered.
        expect(screen.getByRole('button', { name: link!.label })).toBeInTheDocument()
      } else {
        expect(container.querySelector(`a[href="${link!.to}"]`)).toBeTruthy()
      }
    }
  }
})

test('no overflow control survives in the rail', () => {
  renderRail()
  expect(screen.queryByRole('button', { name: /^more$/i })).toBeNull()
})

test('drawer close control stays hidden on desktop and appears at the mobile breakpoint', () => {
  expect(sideRailCss).toMatch(/\.od-shell\s+\.od-rail__close\s*\{\s*display:\s*none;/)
  expect(sideRailCss).toMatch(
    /@media\s*\(max-width:\s*900px\)\s*\{[\s\S]*?\.od-shell\s+\.od-rail__close\s*\{\s*display:\s*inline-flex;/,
  )
  expect(sideRailCss).toMatch(
    /\.od-shell\[data-rail='open'\]\s+\.od-rail\s*\{[^}]*transform:\s*translateX\(0\);[^}]*visibility:\s*visible;/s,
  )
})

test('mobile drawer close control calls the shell close action', async () => {
  const user = userEvent.setup()
  const onCloseDrawer = vi.fn()
  renderRail({ railState: 'open', isMobile: true, onCloseDrawer })

  await user.click(screen.getByRole('button', { name: 'Close' }))

  expect(onCloseDrawer).toHaveBeenCalledOnce()
})

test('every rail destination has a glyph', () => {
  const ids = getPrimaryLinks().map((link) => link.id)
  for (const link of getMoreLinks({ showTrailers: true, showHelp: true, enableVr: true })) {
    ids.push(link.id)
  }
  ids.push('admin')
  for (const id of ids) {
    expect(railIconPaths).toHaveProperty(id)
  }
})

test('panel destinations call back instead of routing', () => {
  const onNavigate = vi.fn()
  renderRail({ onNavigate })

  screen.getByRole('button', { name: 'Chat' }).click()

  expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({ action: 'open-chat' }))
})

test('admin entry appears only for admins', () => {
  const plain = renderRail({ shell: {} })
  expect(plain.container.querySelector('a[href="/admin/dashboard"]')).toBeNull()
  plain.unmount()

  const admin = renderRail({ shell: { isAdmin: true } })
  expect(admin.container.querySelector('a[href="/admin/dashboard"]')).toBeTruthy()
})

test('collapsed rail keeps labels in the accessibility tree', () => {
  // Hiding them with display:none would leave a column of unnamed icons; the
  // stylesheet clips them visually instead, so the names must still be here.
  renderRail({ railState: 'collapsed' })

  expect(screen.getByRole('link', { name: 'Game Catalog' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Wishlist' })).toBeInTheDocument()
})

describe('rail groups fold away', () => {
  /**
   * Twenty-three destinations is a long column and most sessions live in one
   * part of it. The group heading was already there doing nothing, so it became
   * the control rather than adding one beside it.
   */
  function renderRail({
    shell = {},
    ...props
  }: { shell?: Record<string, unknown>; [key: string]: unknown } = {}) {
    return render(
      <MemoryRouter>
        <ShellHarness shell={{ showTrailers: true, showHelp: true, ...shell }}>
          <SideRail {...props} />
        </ShellHarness>
      </MemoryRouter>,
    )
  }

  beforeEach(() => {
    window.localStorage.clear()
  })

  it('every group starts open', () => {
    renderRail()
    const toggles = screen.getAllByRole('button', { expanded: true })
    expect(toggles.length).toBeGreaterThan(0)
  })

  it('folding a group hides its destinations and remembers the choice', async () => {
    const user = userEvent.setup()
    renderRail()

    expect(screen.getByRole('link', { name: 'Wishlist' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Library$/i }))

    expect(screen.queryByRole('link', { name: 'Wishlist' })).toBeNull()
    expect(window.localStorage.getItem('od.rail.collapsedGroups')).toContain('library')
  })

  it('a collapsed rail forces every group open', () => {
    // The headings are visually hidden at icon width, so a folded group would
    // be destinations that vanished with no visible control to bring them back.
    window.localStorage.setItem('od.rail.collapsedGroups', JSON.stringify(['library']))
    renderRail({ railState: 'collapsed' })

    expect(screen.getByRole('link', { name: 'Wishlist' })).toBeInTheDocument()
  })
})
