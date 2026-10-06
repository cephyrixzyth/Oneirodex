import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ArtStudioPage } from './ArtStudioPage'

beforeEach(() => {
  window.history.replaceState(null, '', '/admin/art_studio#studio')
  vi.useRealTimers()
})

function mockFetch(handlers: any) {
  return vi.fn(async (url, init) => {
    const key = `${(init?.method || 'GET').toUpperCase()} ${String(url).split('?')[0]}`
    for (const [match, body] of Object.entries(handlers)) {
      if (key.includes(match) || String(url).includes(match)) {
        const payload = typeof body === 'function' ? body(url, init) : body
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => payload,
        }
      }
    }
    return {
      ok: false,
      status: 404,
      headers: new Headers({ 'content-type': 'application/json' }),

      text: async function () {
        return JSON.stringify(await this.json())
      },
      json: async () => ({ error: `unexpected ${key}` }),
    }
  })
}

test('empty state before a title is entered', () => {
  render(
    <MemoryRouter initialEntries={['/admin/art_studio']}>
      <ArtStudioPage />
    </MemoryRouter>,
  )
  expect(screen.getByTestId('art-studio-empty')).toBeInTheDocument()
  expect(screen.getByText(/Name a title to paint a cover/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^Preview$/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Generate pack/i })).toBeDisabled()
})

test('Art studio tabs switch Studio and Pick & queue', async () => {
  const user = userEvent.setup()
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch({
    '/admin/api/image_queue_list': { images: [], pagination: {} },
    '/admin/api/art-studio/stock': { items: [] },
    '/admin/api/art-studio/system-marks/lab': {
      prompt: 'product icon of grey Nintendo NES',
      url: '/static/library/system-marks/default/nes.webp',
      exists: false,
    },
    '/admin/api/art-studio/system-marks': { items: [], count: 0 },
    '/api/get_libraries': [],
    '/api/library_platforms': [],
    '/api/health/library': { worst: [] },
    '/api/providers': { providers: [] },
    '/api/search_metadata/sources': { sources: [] },
  }) as unknown as typeof globalThis.fetch
  try {
    render(
      <MemoryRouter initialEntries={['/admin/art_studio']}>
        <ArtStudioPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: 'Art studio' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Studio' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText(/System \/ platform|System for art template/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /400×600/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Library default covers/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Backup & stock/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /System marks/i })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /System marks/i }))
    await waitFor(() => {
      expect(screen.getByTestId('system-marks-panel')).toBeInTheDocument()
    })
    expect(screen.getByRole('heading', { name: /Systems hub marks/i })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /Pick & queue/i }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Image queue' })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /Auto-pick best available/i })).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('title input triggers live preview fetch', async () => {
  const user = userEvent.setup()
  const originalFetch = globalThis.fetch
  const calls: any[] = []
  globalThis.fetch = vi.fn(async (url, init) => {
    calls.push({ url: String(url), method: init?.method || 'GET', body: init?.body })
    if (String(url).includes('/admin/api/art-studio/preview')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({
          preview: 'data:image/webp;base64,AAA',
          artistic: true,
          variant: 'tile',
        }),
      }
    }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),

      text: async function () {
        return JSON.stringify(await this.json())
      },
      json: async () => ({}),
    }
  }) as unknown as typeof globalThis.fetch
  try {
    render(
      <MemoryRouter initialEntries={['/admin/art_studio']}>
        <ArtStudioPage />
      </MemoryRouter>,
    )
    const titleInput = screen.getAllByPlaceholderText(/Chrono Trigger/i)[0]
    await user.clear(titleInput)
    await user.type(titleInput, 'Chrono Trigger')
    await waitFor(
      () => {
        const previews: any[] = calls.filter((c) => c.url.includes('/admin/api/art-studio/preview'))
        expect(previews.length).toBeGreaterThanOrEqual(1)
        const body = JSON.parse(previews[previews.length - 1].body)
        expect(body.title).toBe('Chrono Trigger')
        expect(body.width).toBe(400)
        expect(body.height).toBe(600)
      },
      { timeout: 3000 },
    )
    expect(await screen.findByAltText(/Chrono Trigger preview/i)).toBeInTheDocument()
    expect(screen.getByText('Artistic')).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Preview button fetches tile sizes and Generate pack posts generate', async () => {
  const user = userEvent.setup()
  const originalFetch = globalThis.fetch
  const calls: any[] = []
  globalThis.fetch = vi.fn(async (url, init) => {
    calls.push({ url: String(url), method: init?.method || 'GET', body: init?.body })
    if (String(url).includes('/admin/api/art-studio/preview')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({ preview: 'data:image/webp;base64,AAA' }),
      }
    }
    if (String(url).includes('/admin/api/art-studio/generate')) {
      return {
        ok: true,
        status: 201,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({
          pack_id: 'pack-1',
          preview_url: '/static/library/generated/pack-1/tile_400x600.webp',
          files: ['a', 'b', 'c'],
        }),
      }
    }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),

      text: async function () {
        return JSON.stringify(await this.json())
      },
      json: async () => ({}),
    }
  }) as unknown as typeof globalThis.fetch
  try {
    render(
      <MemoryRouter initialEntries={['/admin/art_studio']}>
        <ArtStudioPage />
      </MemoryRouter>,
    )
    const titleInput = screen.getAllByPlaceholderText(/Chrono Trigger/i)[0]
    await user.type(titleInput, 'Star Fox')
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes('/admin/api/art-studio/preview'))).toBe(true)
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^Preview$/i })).toBeEnabled()
    })

    await user.click(screen.getByRole('button', { name: /^Preview$/i }))
    await waitFor(() => {
      const previews: any[] = calls.filter((c) => c.url.includes('/admin/api/art-studio/preview'))
      expect(previews.length).toBeGreaterThanOrEqual(2)
      const bodies = previews.map((c) => JSON.parse(c.body))
      expect(bodies.some((b) => b.width === 200 && b.height === 300)).toBe(true)
      expect(bodies.some((b) => b.width === 400 && b.height === 600)).toBe(true)
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Generate pack/i })).toBeEnabled()
    })
    await user.click(screen.getByRole('button', { name: /Generate pack/i }))
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes('/admin/api/art-studio/generate'))).toBe(true)
    })
    expect(await screen.findByText(/Generated pack pack-1/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Download ZIP/i })).toHaveAttribute(
      'href',
      '/admin/api/art-studio/download/pack-1',
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Backup & stock tab renders catalog and apply posts pack_id', async () => {
  const user = userEvent.setup()
  const posts: any[] = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = vi.fn(async (url, init) => {
    const method = (init?.method || 'GET').toUpperCase()
    const u = String(url)
    if (method === 'POST') {
      posts.push({ url: u, body: init?.body ? JSON.parse(init.body) : null })
    }
    if (u.includes('/admin/api/art-studio/stock') && method === 'GET') {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({
          items: [
            {
              id: 'stock-neon-court',
              label: 'Neon court',
              kind: 'stock',
              pack_id: 'stock-neon-court',
              generated: true,
              urls: { tile: '/static/library/stock/stock-neon-court/tile_400x600.webp' },
            },
          ],
          count: 1,
        }),
      }
    }
    if (u.includes('/admin/api/art-studio/apply')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({ mode: 'fallback' }),
      }
    }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),

      text: async function () {
        return JSON.stringify(await this.json())
      },
      json: async () => ({}),
    }
  }) as unknown as typeof globalThis.fetch
  try {
    window.history.replaceState(null, '', '/admin/art_studio#stock')
    render(
      <MemoryRouter initialEntries={['/admin/art_studio#stock']}>
        <ArtStudioPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('tab', { name: /Backup & stock/i })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await user.click(await screen.findByRole('button', { name: /Neon court/i }))
    await user.click(screen.getByRole('button', { name: /Use as library default/i }))
    await waitFor(() => {
      expect(posts.some((p) => p.url.includes('/admin/api/art-studio/apply'))).toBe(true)
    })
    const apply: any = posts.find((p) => p.url.includes('/admin/api/art-studio/apply'))
    expect(apply.body.pack_id).toBe('stock-neon-court')
    expect(apply.body.mode).toBe('fallback')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('batch placeholders prefer art-studio/batch-generate', async () => {
  const user = userEvent.setup()
  const originalFetch = globalThis.fetch
  const posts: any[] = []
  globalThis.fetch = vi.fn(async (url, init) => {
    const method = (init?.method || 'GET').toUpperCase()
    if (method === 'POST') {
      posts.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : null })
    }
    if (String(url).includes('/api/health/library')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({
          worst: [
            { uuid: 'g1', name: 'No Cover Game', score: 1, issues: [{ code: 'missing_cover' }] },
          ],
        }),
      }
    }
    if (String(url).includes('/admin/api/art-studio/batch-generate')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({
          applied: 1,
          failed: 0,
          results: [{ game_uuid: 'g1', name: 'No Cover Game' }],
          errors: [],
        }),
      }
    }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),

      text: async function () {
        return JSON.stringify(await this.json())
      },
      json: async () => ({}),
    }
  }) as unknown as typeof globalThis.fetch
  try {
    render(
      <MemoryRouter initialEntries={['/admin/art_studio']}>
        <ArtStudioPage />
      </MemoryRouter>,
    )
    await user.click(screen.getByRole('button', { name: /Batch placeholders/i }))
    await user.click(screen.getByRole('button', { name: /Load no-cover list/i }))
    expect(await screen.findByText(/No Cover Game/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Apply placeholders \(1\)/i }))
    await waitFor(() => {
      expect(posts.some((p) => p.url.includes('/admin/api/art-studio/batch-generate'))).toBe(true)
    })
    expect(posts.some((p) => p.url.includes('/admin/api/covers/batch/apply'))).toBe(false)
    expect(await screen.findByText(/Batch generate finished/i)).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})
