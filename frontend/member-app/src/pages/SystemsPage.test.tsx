import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { SystemsPage } from './SystemsPage'

beforeEach(() => {
  window.localStorage.removeItem('od.systems.collapsedFamilies')
})

function mockFetch(payload: any, ok = true) {
  const payloadJson = payload
  const body = JSON.stringify(payloadJson)
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok,
      status: ok ? 200 : 500,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve(payloadJson),
      text: () => Promise.resolve(body),
    }),
  ) as unknown as typeof global.fetch
}

test('renders system tiles linking into library platform filter', async () => {
  mockFetch([
    {
      id: 'NES',
      value: 'NES',
      name: 'Nintendo Entertainment System (NES)',
      game_count: 12,
    },
    {
      id: 'PCWIN',
      value: 'PCWIN',
      name: 'PC Windows',
      game_count: 40,
    },
  ])

  render(
    <MemoryRouter>
      <SystemsPage />
    </MemoryRouter>,
  )

  // TopNav already labels the Systems route — no redundant page H1 here.
  const nes = await screen.findByRole('link', { name: /Nintendo Entertainment System/i })
  expect(screen.queryByRole('heading', { name: 'Systems' })).not.toBeInTheDocument()
  expect(nes).toHaveAttribute('href', '/library?library_platform=NES')
  expect(screen.getByText('12 games')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /PC Windows/i })).toHaveAttribute(
    'href',
    '/library?library_platform=PCWIN',
  )
  expect(screen.getByRole('link', { name: 'Catalog' })).toHaveAttribute(
    'href',
    '/systems/catalog?library_platform=NES',
  )
  // Export packs live in a secondary section — not buried in the intro lede.
  expect(screen.getByRole('heading', { name: 'Export packs' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /ES-DE gamelist/i })).toHaveAttribute(
    'href',
    '/api/export/esde',
  )
  expect(screen.getByRole('link', { name: /Pegasus metadata/i })).toHaveAttribute(
    'href',
    '/api/export/pegasus?platform=Library',
  )
  expect(screen.getByText(/EmulationStation Desktop Edition/i)).toBeInTheDocument()
})

test('shows error retry instead of empty state when fetch fails', async () => {
  mockFetch([], false)

  render(
    <MemoryRouter>
      <SystemsPage />
    </MemoryRouter>,
  )

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load systems.')
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  expect(screen.queryByText(/No library platforms yet/i)).not.toBeInTheDocument()
})

test('manufacturer sections fold and remember the choice', async () => {
  mockFetch([
    {
      id: 'NES',
      value: 'NES',
      name: 'Nintendo Entertainment System (NES)',
      game_count: 12,
    },
    {
      id: 'PS1',
      value: 'PS1',
      name: 'Sony Playstation (PSX)',
      game_count: 8,
    },
  ])

  render(
    <MemoryRouter>
      <SystemsPage />
    </MemoryRouter>,
  )

  const nintendo = await screen.findByRole('button', { name: /Nintendo/i })
  expect(nintendo).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('link', { name: /Nintendo Entertainment System/i })).toBeInTheDocument()

  fireEvent.click(nintendo)
  expect(nintendo).toHaveAttribute('aria-expanded', 'false')
  expect(
    screen.queryByRole('link', { name: /Nintendo Entertainment System/i }),
  ).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Sony Playstation/i })).toBeInTheDocument()
  expect(window.localStorage.getItem('od.systems.collapsedFamilies')).toContain('nintendo')
})

test('prefers themed system-mark WebP for the active data-theme', async () => {
  document.documentElement.setAttribute('data-theme', 'aurora')
  mockFetch([
    {
      id: 'NES',
      value: 'NES',
      name: 'Nintendo Entertainment System (NES)',
      game_count: 3,
    },
  ])

  try {
    const { container } = render(
      <MemoryRouter>
        <SystemsPage />
      </MemoryRouter>,
    )
    await screen.findByRole('link', { name: /Nintendo Entertainment System/i })
    const img = container.querySelector('img.od-systems-tile__mark-img')
    expect(img).toBeTruthy()
    expect(img!.getAttribute('src')).toBe('/static/library/system-marks/aurora/nes.webp')
  } finally {
    document.documentElement.removeAttribute('data-theme')
  }
})

test('canonical themes reuse retired system-mark folders before the SVG fallback', async () => {
  document.documentElement.setAttribute('data-theme', 'greenhouse')
  mockFetch([
    {
      id: 'NES',
      value: 'NES',
      name: 'Nintendo Entertainment System (NES)',
      game_count: 3,
    },
  ])

  try {
    const { container } = render(
      <MemoryRouter>
        <SystemsPage />
      </MemoryRouter>,
    )
    await screen.findByRole('link', { name: /Nintendo Entertainment System/i })
    const image = container.querySelector('img.od-systems-tile__mark-img')!
    expect(image.getAttribute('src')).toBe('/static/library/system-marks/greenhouse/nes.webp')

    fireEvent.error(image)
    expect(container.querySelector('img.od-systems-tile__mark-img')?.getAttribute('src')).toBe(
      '/static/library/system-marks/forest/nes.webp',
    )
    fireEvent.error(container.querySelector('img.od-systems-tile__mark-img')!)
    expect(container.querySelector('img.od-systems-tile__mark-img')).toBeNull()
    expect(container.querySelector('.od-systems-tile__mark svg')).toBeInTheDocument()
  } finally {
    document.documentElement.removeAttribute('data-theme')
  }
})
