import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { ShellConfigProvider } from '@oneirodex/ui'
import { VrPage } from './VrPage'

afterEach(() => vi.unstubAllGlobals())

const emptyCatalogResponse = () => ({
  ok: true,
  status: 200,
  headers: new Headers({ 'content-type': 'application/json' }),
  text: async () => JSON.stringify({ games: [], total: 0, page: 1, pages: 1 }),
  json: async () => ({ games: [], total: 0, page: 1, pages: 1 }),
})

test('VR catalog waits for safe browser control before making a private request', async () => {
  const fetchMock = vi.fn(async (_url: RequestInfo | URL) => emptyCatalogResponse())
  const serviceWorker = {
    controller: { scriptURL: `${location.origin}/vr/sw.js` },
    register: vi.fn(async () => ({})),
  }
  let ready!: (safe: boolean) => void
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('navigator', { serviceWorker })
  vi.stubGlobal(
    'odPwaPrivacyReady',
    new Promise<boolean>((resolve) => {
      ready = resolve
    }),
  )
  render(
    <ShellConfigProvider value={{ enableNewChrome: true }}>
      <MemoryRouter>
        <VrPage />
      </MemoryRouter>
    </ShellConfigProvider>,
  )
  expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/vr/'))).toHaveLength(0)
  await act(async () => {
    serviceWorker.controller.scriptURL = `${location.origin}/sw.js`
    ready(true)
  })
  await screen.findByText('No games are available for VR browsing yet.')
  expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/vr/'))).toHaveLength(1)
  expect(serviceWorker.register).not.toHaveBeenCalled()
})

test('VR refuses private requests when browser privacy migration fails', async () => {
  const fetchMock = vi.fn(async (_url: RequestInfo | URL) => emptyCatalogResponse())
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('navigator', {
    serviceWorker: {
      controller: { scriptURL: `${location.origin}/vr/sw.js` },
      register: vi.fn(async () => ({})),
    },
  })
  vi.stubGlobal('odPwaPrivacyReady', Promise.resolve(false))
  render(
    <ShellConfigProvider value={{ enableNewChrome: true }}>
      <MemoryRouter>
        <VrPage />
      </MemoryRouter>
    </ShellConfigProvider>,
  )
  await screen.findByRole('alert')
  expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/vr/'))).toHaveLength(0)
})

test('VR compatibility filters render in the shared THN view strip', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async () => JSON.stringify({ games: [], total: 0, page: 1, pages: 1 }),
    json: async () => ({ games: [], total: 0, page: 1, pages: 1 }),
  }))
  vi.stubGlobal('fetch', fetchMock)
  render(
    <ShellConfigProvider value={{ enableNewChrome: true }}>
      <MemoryRouter initialEntries={['/vr']}>
        <VrPage />
      </MemoryRouter>
    </ShellConfigProvider>,
  )

  const views = screen.getByRole('group', { name: 'Views' })
  expect(views).toHaveClass('od-seg')
  expect(views).toContainElement(screen.getByRole('button', { name: 'Native VR' }))
  expect(screen.queryByRole('group', { name: 'Way to play' })).toBeNull()
  await user.click(screen.getByRole('button', { name: 'Community profile' }))
  expect(screen.getByRole('button', { name: 'Community profile' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
})
