import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach } from 'vitest'
import { DashboardPage } from './DashboardPage'
import { DASHBOARD_STORAGE_KEY } from '../components/dashboardLayout'

beforeEach(() => {
  const store = new Map()
  vi.stubGlobal('localStorage', {
    getItem: (key: any) => (store.has(key) ? store.get(key) : null),
    setItem: (key: any, value: any) => {
      store.set(key, String(value))
    },
    removeItem: (key: any) => {
      store.delete(key)
    },
    clear: () => store.clear(),
  })
})

afterEach(() => {
  cleanup()
  window.localStorage?.removeItem?.(DASHBOARD_STORAGE_KEY)
  vi.unstubAllGlobals()
})

function mockSummary(overrides = {}) {
  globalThis.fetch = vi.fn(async (url: any): Promise<any> => {
    if (String(url).includes('/admin/api/ops/summary')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({
          as_of: new Date().toISOString(),
          issues: { overall: 'warn', items: [] },
          host: {
            load_avg: { 1: 0.2, 5: 0.3, 15: 0.4 },
            process: { rss_bytes: 1024, pid: 9 },
            db_ping_ms: 12,
            cpu: { percent: 5 },
            memory: { percent: 20, used: 1, total: 4 },
            disk_games: { percent: 96 },
          },
          library: {
            libraries: 2,
            games: 10,
            unmatched_folders: 1,
            health: { score: 81, grade: 'good', factors: [] },
          },
          scans: { active_count: 1, jobs: [{ library: 'Main', progress: 40 }] },
          services: {
            awake: { status: 'ok', check_ms: 3 },
            companions: {
              online: 1,
              registered: 2,
              by_kind: { desktop: { online: 1, registered: 2 } },
              last_seen: { within_1h: 1, stale: 0 },
            },
          },
          recent_errors: [],
          ...overrides,
        }),
      }
    }
    throw new Error(`unexpected fetch ${url}`)
  }) as unknown as typeof globalThis.fetch
}

test('DashboardPage Updated timestamp is a hover tooltip on refresh', async () => {
  mockSummary()
  const trail = document.createElement('div')
  trail.id = 'od-admin-topbar-trail'
  const pageSlot = document.createElement('div')
  pageSlot.id = 'od-admin-topbar-slot'
  document.body.appendChild(trail)
  document.body.appendChild(pageSlot)
  try {
    const { container } = render(<DashboardPage />)
    const refresh = await screen.findByRole('button', { name: 'Refresh dashboard' })
    expect(trail.contains(refresh)).toBe(true)
    expect(within(trail).queryByRole('button', { name: 'Reset layout' })).toBeNull()
    expect(within(pageSlot).getByRole('button', { name: 'Reset layout' })).toBeInTheDocument()
    const wrap = refresh.closest('.od-ops-refresh-wrap')
    expect(wrap).toBeTruthy()
    const asOf = within(wrap as HTMLElement).getByRole('tooltip')
    expect(asOf.textContent).toMatch(/Updated /)
    expect(refresh.getAttribute('aria-describedby')).toBe(asOf.id)
    expect(container.querySelector('.od-ops-status__trail')).toBeNull()
    expect(container.querySelector('.od-admin-dashboard-footer')).toBeNull()
  } finally {
    trail.remove()
    pageSlot.remove()
  }
})

test('DashboardPage metric labels stay title case (not ALL CAPS)', async () => {
  mockSummary()
  const { container } = render(<DashboardPage />)
  await screen.findByRole('button', { name: 'Refresh dashboard' })
  const labels = [...container.querySelectorAll('.od-ops-metric__label')].map((n) => n.textContent)
  expect(labels).toContain('Libraries')
  expect(labels).toContain('Library health')
  expect(labels.some((label) => label === 'LIBRARIES')).toBe(false)
})

test('DashboardPage shows library health tile when library.health present', async () => {
  mockSummary({
    issues: { overall: 'good', items: [] },
    host: {
      load_avg: null,
      process: null,
      db_ping_ms: null,
      cpu: { percent: 5 },
      memory: { percent: 20, used: 1, total: 4 },
      disk_games: { percent: 40 },
    },
    library: {
      libraries: 2,
      games: 10,
      unmatched_folders: 1,
      health: {
        score: 81,
        grade: 'good',
        factors: [{ id: 'missing_cover', label: 'Missing cover', count: 2 }],
      },
    },
    scans: { active_count: 0, jobs: [] },
  })
  const { container } = render(<DashboardPage />)
  await screen.findByRole('button', { name: 'Refresh dashboard' })
  await waitFor(() => {
    const health = [...container.querySelectorAll('.od-ops-metric')].find(
      (node) => node.querySelector('.od-ops-metric__label')?.textContent === 'Library health',
    )
    expect(health).toBeTruthy()
    expect(health!.querySelector('.od-ops-metric__value')).toHaveTextContent('81 · good')
  })
})

test('DashboardPage renders Action required and Warning / Info folds', async () => {
  mockSummary({
    issues: {
      overall: 'bad',
      items: [
        { id: 'a1', severity: 'bad', category: 'action', message: 'Disk critical' },
        { id: 'w1', severity: 'warn', category: 'warning', message: 'Base disk 100% used' },
      ],
    },
  })
  render(<DashboardPage />)
  expect(await screen.findByText('Needs attention')).toBeInTheDocument()
  expect(screen.getByText('Action required')).toBeInTheDocument()
  expect(screen.getByText('Warning / Info')).toBeInTheDocument()
  expect(screen.getByText('Disk critical')).toBeInTheDocument()
  expect(screen.getByText('Base disk 100% used')).toBeInTheDocument()
})

test('DashboardPage disk-only issues stay Warning / Info', async () => {
  mockSummary({
    issues: {
      overall: 'warn',
      items: [
        {
          id: 'disk_games_critical',
          severity: 'warn',
          category: 'warning',
          message: 'Games disk 100% used',
        },
      ],
    },
  })
  render(<DashboardPage />)
  expect(await screen.findByText('Degraded')).toBeInTheDocument()
  expect(screen.getByText('Warning / Info')).toBeInTheDocument()
  expect(screen.queryByText('Action required')).toBeNull()
})

test('DashboardPage health banner stays neutral while its first summary loads', () => {
  globalThis.fetch = vi.fn(() => new Promise(() => {})) as unknown as typeof globalThis.fetch
  render(<DashboardPage />)
  const health = screen.getByRole('region', { name: 'Health' })
  expect(health).toHaveAttribute('aria-busy', 'true')
  expect(within(health).getByText('Checking health…')).toBeInTheDocument()
  expect(within(health).queryByText('All systems healthy')).toBeNull()
})

test('DashboardPage health banner reports unavailable after the first summary fails', async () => {
  globalThis.fetch = vi.fn(async () => {
    throw new Error('offline')
  }) as unknown as typeof globalThis.fetch
  render(<DashboardPage />)
  const health = screen.getByRole('region', { name: 'Health' })
  expect(await within(health).findByText('Health status unavailable')).toBeInTheDocument()
  expect(within(health).queryByText('All systems healthy')).toBeNull()
})

test('DashboardPage board exposes reset layout', async () => {
  mockSummary()
  // Centre page slot matches Users Invites/Support / member Library actions.
  const pageSlot = document.createElement('div')
  pageSlot.id = 'od-admin-topbar-slot'
  document.body.appendChild(pageSlot)
  render(<DashboardPage />)
  const reset = await screen.findByRole('button', { name: 'Reset layout' })
  expect(reset).toBeInTheDocument()
  expect(reset).toHaveClass('od-cbtn')
  expect(pageSlot.contains(reset)).toBe(true)
  expect(document.querySelector('.od-dash__toolbar')).toBeNull()
  expect(document.querySelector('.od-dash__board')).toBeTruthy()
  pageSlot.remove()
})
