import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { RetroAchievementsPanel } from './RetroAchievementsPanel'
import { showToast } from '../utils/toast'

vi.mock('../utils/toast', () => ({
  showToast: vi.fn(),
}))

function jsonResponse(body: any, ok = true, status = 200) {
  return {
    ok,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => body,
  }
}

const CONFIGURED = {
  ok: true,
  configured: true,
  username: 'household',
  has_key: true,
  supported_platforms: ['GBA', 'NES', 'SNES'],
  consoles: [
    {
      platform: 'NES',
      console_id: 7,
      indexed_hashes: 1200,
      index_fetched_at: '2026-09-17T10:00:00Z',
      matched_games: 14,
    },
  ],
}

function mockApi({
  status = CONFIGURED,
  matchOk = true,
}: { status?: any; matchOk?: boolean } = {}) {
  globalThis.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    if (String(url).includes('/api/retroachievements/status')) {
      return jsonResponse(status)
    }
    if (String(url).includes('/api/retroachievements/match') && method === 'POST') {
      if (!matchOk) {
        return jsonResponse({ ok: false, error: 'RetroAchievements is not configured' }, false, 403)
      }
      return jsonResponse({
        ok: true,
        platform: 'NES',
        console_id: 7,
        indexed_hashes: 1200,
        considered: 30,
        hashed: 30,
        matched: 14,
      })
    }
    return jsonResponse({}, false, 404)
  }) as unknown as typeof globalThis.fetch
  return globalThis.fetch
}

afterEach(() => {
  vi.restoreAllMocks()
})

test('unconfigured points to Integrations setup, and offers no Match', async () => {
  mockApi({
    status: {
      ok: true,
      configured: false,
      username: null,
      has_key: false,
      supported_platforms: ['NES'],
      consoles: [],
    },
  })
  render(<RetroAchievementsPanel />)
  expect(await screen.findByTestId('ra-unconfigured')).toHaveTextContent(/Admin → Integrations/)
  expect(screen.queryByRole('button', { name: /^Match/ })).not.toBeInTheDocument()
})

test('a half-configured install says which half is missing', async () => {
  mockApi({
    status: {
      ok: true,
      configured: false,
      username: null,
      has_key: true,
      supported_platforms: ['NES'],
      consoles: [],
    },
  })
  render(<RetroAchievementsPanel />)
  expect(await screen.findByTestId('ra-unconfigured')).toHaveTextContent(
    /key is present; the username is missing/i,
  )
})

test('configured lists each system with its index and matched count', async () => {
  mockApi()
  render(<RetroAchievementsPanel />)
  expect(await screen.findByText('household')).toBeInTheDocument()
  const row = (await screen.findByRole('row', { name: /NES/ })).textContent
  expect(row).toContain('1200')
  expect(row).toContain('14')
})

test('Match posts the platform and reports what it did', async () => {
  const fetchSpy = mockApi()
  render(<RetroAchievementsPanel />)
  const button = await screen.findByRole('button', { name: 'Match NES' })
  await userEvent.click(button)
  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/retroachievements/match',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ platform: 'NES', rehash: false }),
      }),
    )
  })
  expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/14 of 30 matched/), 'success')
  expect(await screen.findByTestId('ra-last-run')).toHaveTextContent(/30 considered/)
})

test('a refused match surfaces the reason instead of a silent no-op', async () => {
  mockApi({ matchOk: false })
  render(<RetroAchievementsPanel />)
  await userEvent.click(await screen.findByRole('button', { name: 'Match NES' }))
  await waitFor(() => {
    expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/not configured/i), 'error')
  })
})
