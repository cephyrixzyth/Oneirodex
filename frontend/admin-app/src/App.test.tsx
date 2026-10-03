import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach } from 'vitest'
import { App, resolveRenderMode } from './App'

// --- GT-A3: declared render mode ------------------------------------------

function mountRoot({
  render: mode,
  legacyHtml = '',
}: { render?: string; legacyHtml?: string } = {}) {
  const root = document.createElement('div')
  root.id = 'admin-app-root'
  if (mode) root.dataset.adminRender = mode
  document.body.appendChild(root)

  const legacy = document.createElement('div')
  legacy.id = 'admin-legacy-content'
  legacy.innerHTML = legacyHtml
  document.body.appendChild(legacy)

  return root
}

afterEach(() => {
  document.getElementById('admin-app-root')?.remove()
  document.getElementById('admin-legacy-content')?.remove()
})

// A Jinja body full of forms and cards used to make the React page vanish.
// With an explicit declaration it no longer can — this is the actual UID
// behind "admin pages feel inconsistent".
const HEAVY_LEGACY_BODY = `
  <div class="card"><form><table><tr><td>
    Server settings form with plenty of text to clear the 40 character floor.
  </td></tr></table></form></div>
`

test('declared spa wins even when the Jinja body looks legacy', () => {
  mountRoot({ render: 'spa', legacyHtml: HEAVY_LEGACY_BODY })
  expect(resolveRenderMode()).toBe('spa')
})

test('declared legacy wins even when the Jinja body is empty', () => {
  mountRoot({ render: 'legacy', legacyHtml: '' })
  expect(resolveRenderMode()).toBe('legacy')
})

test('auto falls back to the old heuristic for unmigrated templates', () => {
  mountRoot({ render: 'auto', legacyHtml: HEAVY_LEGACY_BODY })
  expect(resolveRenderMode()).toBe('legacy')

  document.getElementById('admin-legacy-content')!.innerHTML = ''
  expect(resolveRenderMode()).toBe('spa')
})

test('a missing attribute behaves like auto', () => {
  mountRoot({ legacyHtml: HEAVY_LEGACY_BODY })
  expect(resolveRenderMode()).toBe('legacy')
})

test('an unknown value warns and falls back rather than blanking the page', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
  mountRoot({ render: 'typo', legacyHtml: '' })
  expect(resolveRenderMode()).toBe('spa')
  expect(warn).toHaveBeenCalled()
  warn.mockRestore()
})

test('integrations hub shows grouped cards', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = vi.fn(async (url) => {
    if (String(url).includes('/api/admin/integrations/inventory')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({
          integrations: [
            {
              id: 'steamgriddb',
              name: 'SteamGridDB',
              category: 'artwork',
              status: 'configured',
              configured: true,
              admin_href: '/admin/integrations#steamgriddb',
              settings_href: '/admin/integrations#steamgriddb',
              notes: 'Cover / hero art',
            },
            {
              id: 'igdb',
              name: 'IGDB',
              category: 'metadata',
              status: 'configured',
              configured: true,
              admin_href: '/admin/integrations#igdb',
              settings_href: '/admin/igdb_settings',
              notes: 'Primary game metadata',
            },
            {
              id: 'arr_prowlarr',
              name: 'Prowlarr',
              category: 'acquire',
              status: 'available',
              configured: false,
              admin_href: '/admin/arr',
              settings_href: '/admin/arr',
              notes: 'Acquire connector',
            },
          ],
          count: 3,
        }),
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }) as unknown as typeof globalThis.fetch
  try {
    render(
      <MemoryRouter initialEntries={['/admin/integrations']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: 'Integrations' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'IGDB' })).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Artwork & secondary metadata' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'SMTP' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'OIDC' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'LiveKit' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Acquire / Arr' })).toBeInTheDocument()
    // "Export packs" left Integrations with GT-B8 — it writes a file for another
    // emulator frontend to read, which is emulation, not a service we talk to.
    expect(screen.queryByRole('heading', { name: 'Export packs' })).toBeNull()
    expect(screen.getByRole('heading', { name: 'Support' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'IGDB settings' })).toHaveAttribute(
      'href',
      '/admin/igdb_settings',
    )
    // The two raw /api/export links went with the card (GT-B8): they were
    // downloads sitting in a list of destinations, under names that meant
    // nothing unless you already ran those launchers.
    expect(screen.queryByRole('link', { name: /ES-DE/i })).toBeNull()
    expect(screen.queryByRole('link', { name: /Pegasus/i })).toBeNull()
    expect(await screen.findByRole('heading', { name: 'Provider inventory' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Artwork' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Metadata' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Acquire' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'SteamGridDB' })).toHaveAttribute(
      'href',
      '/admin/integrations#steamgriddb',
    )
    const igdbLinks = screen.getAllByRole('link', { name: 'IGDB' })
    expect(igdbLinks.some((el) => el.getAttribute('href') === '/admin/igdb_settings')).toBe(true)
    expect(screen.getByText(/Cover \/ hero art/i)).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

// Still valid after the chrome change (GT-B2): the assertions are about what is
// offered, not where. The nav landmark is now the rail rather than bar one, and
// it keeps the same "Admin" accessible name, so these read unchanged.
test('renders admin brand and primary nav', () => {
  render(
    <MemoryRouter initialEntries={['/admin/dashboard']}>
      <App />
    </MemoryRouter>,
  )
  expect(screen.getByText('Oneirodex Admin')).toBeInTheDocument()
  const nav = screen.getByRole('navigation', { name: 'Admin' })
  expect(nav.querySelector('a[href="/admin/dashboard"]')).toHaveTextContent('Dashboard')
  // Settings unfolds into four icon sub-sections; their children live in the top bar.
  const settingsToggle = screen.getByRole('button', { name: 'Settings' })
  expect(settingsToggle).toHaveClass('od-rail__group-toggle')
  fireEvent.click(settingsToggle)
  for (const title of ['Library & matching', 'Play & emulation', 'Presentation', 'Extend']) {
    expect(screen.getByRole('link', { name: title })).toBeInTheDocument()
  }

  // Libraries & scans is a hub of sibling pages again.
  const librariesToggle = screen.getByRole('button', { name: 'Libraries & scans' })
  expect(librariesToggle).toHaveClass('od-rail__group-toggle')
  fireEvent.click(librariesToggle)
  expect(nav.querySelector('a[href="/libraries"]')).toHaveTextContent('Libraries')
  expect(nav.querySelector('a[href="/scan_management?active_tab=auto"]')).toHaveTextContent('Scan')
  expect(nav.querySelector('a[href="/scan_management?active_tab=manual"]')).toBeNull()
})

test('users route shows React roster', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = vi.fn(async (url) => {
    if (String(url).includes('/admin/api/users')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({
          users: [
            {
              id: 1,
              name: 'Ada',
              email: 'ada@example.com',
              role: 'admin',
              state: true,
              is_email_verified: true,
            },
          ],
        }),
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }) as unknown as typeof globalThis.fetch
  try {
    render(
      <MemoryRouter initialEntries={['/admin/users']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Ada')).toBeInTheDocument()
    expect(screen.getByText('ada@example.com')).toBeInTheDocument()
    // The classic editor is gone (GT-B18) — two editors for the same rows meant
    // two behaviours to keep in step. The React roster is the only one now.
    expect(screen.queryByRole('link', { name: /Classic user editor/i })).toBeNull()
  } finally {
    globalThis.fetch = originalFetch
  }
})
