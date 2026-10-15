import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, vi } from 'vitest'

import { TopBar } from './TopBar'
import { ShellHarness } from '../testShell'

/**
 * Bar one, reduced to page scope (GT-B2).
 *
 * The rail owns destinations now, so there is little structure left here worth
 * pinning — but the one control the bar still owns outright is the rail toggle,
 * and it had no coverage in either shell while quietly reporting the wrong
 * state.
 */

function renderTopBar(props = {}) {
  const initialEntries = (props as { initialEntries?: string[] }).initialEntries || ['/library']
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <ShellHarness shell={{ username: 'ada' }}>
        <TopBar {...props} />
      </ShellHarness>
    </MemoryRouter>,
  )
}

test('legacy account destinations open their React panel after direct entry', async () => {
  window.history.replaceState({}, '', '/')
  const originalFetch = globalThis.fetch
  globalThis.fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      username: 'ada',
      email: 'ada@example.com',
      role: 'user',
      avatar_path: '/avatar.svg',
      stock_avatars: [],
      invite_quota: 0,
      invites_used: 0,
      invites_remaining: 0,
      smtp_enabled: false,
    }),
  })) as unknown as typeof fetch
  try {
    renderTopBar({ initialEntries: ['/library?account=password'] })
    expect(await screen.findByRole('heading', { name: 'Change password' })).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('legacy invite destination opens the shared React invite panel', async () => {
  window.history.replaceState({}, '', '/')
  const originalFetch = globalThis.fetch
  globalThis.fetch = vi.fn(async (input) => ({
    ok: true,
    json: async () =>
      String(input).includes('/api/account/invites')
        ? {
            invites: [],
            quota: 5,
            remaining: 5,
            smtp_enabled: false,
            ttl_hours: 48,
            site_url_configured: true,
          }
        : {
            username: 'ada',
            email: 'ada@example.com',
            role: 'user',
            avatar_path: '/avatar.svg',
            stock_avatars: [],
            invite_quota: 5,
            invites_used: 0,
            invites_remaining: 5,
            smtp_enabled: false,
          },
  })) as unknown as typeof fetch
  try {
    renderTopBar({ initialEntries: ['/library?account=invites'] })
    expect(await screen.findByRole('button', { name: 'Create invite link' })).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('legacy preferences destination opens the shared React dialog', () => {
  const dispatch = vi.spyOn(window, 'dispatchEvent')
  try {
    renderTopBar({ initialEntries: ['/library?preferences=1'] })
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: 'od:open-preferences' }))
  } finally {
    dispatch.mockRestore()
  }
})

test('the rail toggle reports whether the rail is showing', () => {
  // The rail has three states and this one button drives all of them, so
  // `=== 'open'` was the wrong test: 'open' is the mobile drawer only, which
  // left aria-expanded permanently false on desktop — announcing a collapsed
  // rail while it sat there expanded with its labels showing. Shown is 'open'
  // or 'expanded'; 'collapsed' is the only state that is not.
  //
  // partials/topbar.html and its base.html handler have always had this right,
  // which is what made the divergence worth a test: one chrome, three
  // implementations, and the two React ones disagreed with the correct one.
  for (const [railState, expected] of [
    ['expanded', 'true'],
    ['open', 'true'],
    ['collapsed', 'false'],
  ]) {
    const { unmount } = renderTopBar({ railState })
    expect(screen.getByRole('button', { name: 'Toggle navigation' })).toHaveAttribute(
      'aria-expanded',
      expected,
    )
    unmount()
  }
})

test('the toggle keeps one stable name across states', () => {
  // A disclosure button carries its state in aria-expanded, not in a name that
  // changes underneath the user — a control renaming itself mid-interaction is
  // what makes a rail toggle read as two different buttons.
  const { unmount } = renderTopBar({ railState: 'expanded' })
  expect(screen.getByRole('button', { name: 'Toggle navigation' })).toBeInTheDocument()
  unmount()

  renderTopBar({ railState: 'collapsed' })
  expect(screen.getByRole('button', { name: 'Toggle navigation' })).toBeInTheDocument()
})
