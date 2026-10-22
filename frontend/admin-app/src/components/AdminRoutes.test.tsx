import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { AdminRoutes } from './AdminRoutes'

/**
 * PR-4 (c): the explicit route table must render, for every path, the same page
 * the old `resolveAdminPage` → `renderAdminKind` switch returned. This is the
 * "no URL changed" guard — one row per branch of the old switch.
 */

const originalFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mountAt(path: any) {
  // Pages fire data fetches on mount; a generic empty-OK stub keeps them from
  // throwing while we assert on the synchronous <h1>.
  globalThis.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => ({}),
    text: async () => '',
  })) as unknown as typeof globalThis.fetch
  render(
    <MemoryRouter initialEntries={[path]}>
      <AdminRoutes />
    </MemoryRouter>,
  )
}

function LocationProbe() {
  const location = useLocation()
  return (
    <output data-testid="current-location">
      {location.pathname}
      {location.search}
      {location.state?.linkSuccess || ''}
    </output>
  )
}

const CASES = [
  ['/admin', 'Dashboard'],
  ['/admin/dashboard', 'Dashboard'],
  ['/admin/support', 'Support inbox'],
  ['/admin/help', 'Admin help'],
  ['/admin/invites', 'Invites'],
  ['/admin/whitelist', 'Whitelist'],
  ['/admin/manage_invites', 'Invites'],
  ['/admin/settings', 'Settings'],
  ['/admin/storage', 'Storage / hardlinks'],
  ['/admin/smtp_settings', 'SMTP'],
  ['/admin/scan_match', 'Scan / match policy'],
  ['/admin/remote_play', 'Remote play'],
  ['/admin/quality_profiles', 'Quality Profiles'],
  ['/admin/announcements', 'Announcements'],
  ['/admin/integrations', 'Integrations'],
  ['/admin/scan-jobs', 'Scan jobs'],
  ['/admin/scan-controls', 'Automatic scan'],
  ['/add_game_manual', 'Identify game'],
  ['/game_edit/123e4567-e89b-12d3-a456-426614174000', 'Edit game entry'],
  ['/edit_game_images/123e4567-e89b-12d3-a456-426614174000', 'Edit game images'],
  ['/admin/unmatched', 'Unmatched folders'],
  ['/admin/themes/readme', 'Creating Your Own Theme'],
  ['/admin/art_studio', 'Art studio'],
  ['/admin/images', 'Art & images'],
  ['/admin/extensions', 'File Extensions'],
  ['/admin/ops', 'Ops'],
  ['/admin/ops/history', 'Ops'],
  // libraries family — preserve the legacy direct-add entry point
  ['/libraries', 'Libraries'],
  ['/admin/library/add', 'Create library'],
  ['/admin/library/edit/123e4567-e89b-12d3-a456-426614174000', 'Edit library'],
  ['/libraries/legacy', 'Libraries & scans'],
  ['/admin/library/tools', 'Libraries & scans'],
  ['/scan_management?active_tab=auto', 'Automatic scan'],
  ['/scan_management?active_tab=manual', 'Manual scan / identify'],
  ['/scan_manual_folder', 'Manual scan / identify'],
  ['/scan_management?active_tab=jobs', 'Scan jobs'],
  ['/scan_management?active_tab=unmatched', 'Unmatched folders'],
  ['/scan_management?active_tab=scan_filters', 'Game scanning filters'],
  ['/scan_management?active_tab=file_extensions', 'File Extensions'],
  ['/admin/ai', 'AI assist'],
  ['/admin/arr', 'Arr module'],
  ['/admin/detail_layout', 'Detail layout'], // React body since H-D.5; same h1 as the card
  // unknown admin path -> the old switch default
  ['/admin/something-unrouted', 'Admin'],
]

describe('AdminRoutes path -> page', () => {
  test.each(CASES)('%s renders "%s"', (path, heading) => {
    mountAt(path)
    expect(screen.getByRole('heading', { name: heading, level: 1 })).toBeInTheDocument()
  })

  test('automatic scan tab does not append the manual identification page', () => {
    mountAt('/scan_management?active_tab=auto')
    expect(screen.getByRole('heading', { name: 'Automatic scan', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Manual identify', level: 2 })).toBeNull()
    expect(screen.getByRole('button', { name: 'Start scan' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'List games to identify' })).toBeNull()
    expect(screen.queryByText('Dupe glance')).toBeNull()
  })

  test('manual identify tab renders its controls without automatic scan options', () => {
    mountAt('/scan_management?active_tab=manual')
    expect(
      screen.getByRole('heading', { name: 'Manual scan / identify', level: 1 }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Manual identify', level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'List games to identify' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start scan' })).toBeNull()
    expect(screen.queryByLabelText('Repeat schedule')).toBeNull()
  })

  test('/admin/library/add opens the create form directly', () => {
    mountAt('/admin/library/add')
    expect(screen.getByRole('heading', { name: 'Add one library', level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to libraries' })).toHaveAttribute(
      'href',
      '/libraries',
    )
    expect(
      screen.getByRole('button', { name: 'Create library' }),
    ).toBeInTheDocument()
  })

  test('catch-all lede matches the old switch default', () => {
    mountAt('/admin/nope')
    expect(screen.getByText('Pick a section from the rail on the left.')).toBeInTheDocument()
  })

  test('scan-management unmatched route keeps its URL and uses the paginated scan table', async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => [],
      text: async () => '',
    })) as unknown as typeof globalThis.fetch
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/scan_management',
            search: '?active_tab=unmatched',
            state: { linkSuccess: 'link completed' },
          },
        ]}
      >
        <AdminRoutes />
        <LocationProbe />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: 'Unmatched folders' })).toBeInTheDocument()
    expect(screen.getByTestId('current-location')).toHaveTextContent(
      '/scan_management?active_tab=unmatched',
    )
    expect(await screen.findByText('link completed')).toBeInTheDocument()
    expect(screen.queryByText('Dupe glance')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Unmatched folder filters and results')).toBeInTheDocument()
  })

  test('Admin Help internal navigation stays in the SPA', () => {
    mountAt('/admin/help')
    fireEvent.click(screen.getByRole('link', { name: /Libraries and scans/i }))
    expect(screen.getByRole('heading', { name: 'Libraries', level: 1 })).toBeInTheDocument()
  })
})
