import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../App'
import { ExtensionsPage } from './ExtensionsPage'

function mockFetch(handlers: any) {
  return vi.fn(async (url, init) => {
    const method = (init?.method || 'GET').toUpperCase()
    const key = `${method} ${String(url)}`
    for (const [match, fn] of handlers) {
      if (key.includes(match) || String(url).includes(match)) {
        const result = await fn(url, init, method)
        if (result) return result
      }
    }
    throw new Error(`unexpected fetch ${method} ${url}`)
  })
}

function jsonOk(body: any, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => body,
  }
}

test('ExtensionsPage lists extensions and supports add/remove happy path', async () => {
  const user = userEvent.setup()
  const originalFetch = globalThis.fetch
  let store = [
    { id: 1, value: 'zip' },
    { id: 2, value: 'iso' },
    { id: 3, value: 'nes' },
  ]
  let nextId = 4

  globalThis.fetch = mockFetch([
    [
      '/api/file_types/allowed',
      async (_url: any, init: any, method: any) => {
        if (method === 'GET') return jsonOk(store)
        if (method === 'POST') {
          const body = init?.body ? JSON.parse(init.body) : {}
          const row = { id: nextId++, value: String(body.value || '').toLowerCase() }
          store = [...store, row].sort((a, b) => a.value.localeCompare(b.value))
          return jsonOk(row, 201)
        }
        if (method === 'DELETE') {
          const body = init?.body ? JSON.parse(init.body) : {}
          store = store.filter((row) => row.id !== Number(body.id))
          return jsonOk({ success: true })
        }
        return null
      },
    ],
  ])

  try {
    render(<ExtensionsPage />)
    expect(await screen.findByRole('heading', { name: 'File Extensions' })).toBeInTheDocument()
    // The heading is written in the loading branch as well as the loaded one, so
    // awaiting it says nothing about the fetch having resolved — it can be
    // satisfied by the skeleton. The chips only exist once `loading` flips, so
    // the first one gets `findByText`. Everything below it comes out of the same
    // `sections.map` in that same commit and can stay synchronous.
    expect(await screen.findByText('.zip')).toBeInTheDocument()
    expect(screen.getByText('.iso')).toBeInTheDocument()
    expect(screen.getByText('.nes')).toBeInTheDocument()
    const quickAdd = screen.getByRole('button', { name: 'Add .7z (Archives)' })
    expect(quickAdd.closest('[role="listitem"]')).toBeInTheDocument()
    expect(quickAdd).not.toHaveAttribute('role', 'listitem')
    expect(screen.getByRole('heading', { name: 'Archives' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Disc images' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Cartridge / ROM' })).toBeInTheDocument()

    await user.type(screen.getByRole('textbox', { name: 'File extension to add' }), '7z')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/file_types/allowed',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    expect(await screen.findByText('.7z')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove .iso' }))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/file_types/allowed',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Remove .iso' })).not.toBeInTheDocument()
    })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('App route /admin/extensions mounts Extensions UI', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetch([
    [
      '/api/file_types/allowed',
      async (_url: any, _init: any, method: any) => (method === 'GET' ? jsonOk([]) : null),
    ],
  ])
  try {
    render(
      <MemoryRouter initialEntries={['/admin/extensions']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: 'File Extensions' })).toBeInTheDocument()
    // Same reason as the chip await above, and this test mounts the full App
    // router on top of it, so the page arrives over more commits still. The lede
    // is loaded-branch-only; `findByText` waits for it instead of asserting that
    // it committed alongside a heading the skeleton already satisfied.
    expect(await screen.findByText(/library scan recognition/i)).toBeInTheDocument()
  } finally {
    globalThis.fetch = originalFetch
  }
})
