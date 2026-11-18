import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { PcCheatsPanel } from './PcCheatsPanel'
import { stubFetch } from '../testJsonResponse'

const PAYLOAD = {
  ok: true,
  stance: 'Notes only — Oneirodex never modifies game files.',
  methods: [
    { id: 'console', label: 'In-game console command' },
    { id: 'config', label: 'Config / ini file edit' },
  ],
  cheats: [
    {
      id: 1,
      label: 'God mode',
      method: 'console',
      payload: 'sv_cheats 1; god',
      notes: 'Open console with ~',
      single_player_only: true,
    },
  ],
}

function mockFetch(payload: any, ok = true) {
  stubFetch(async () => ({ ok, status: ok ? 200 : 400, json: async () => payload }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

test('does not render on a RetroArch title', () => {
  mockFetch(PAYLOAD)
  const { container } = render(<PcCheatsPanel gameUuid="abc" cheatSurface="retroarch" />)
  // The two cheat surfaces must never both appear for one game.
  expect(container).toBeEmptyDOMElement()
  expect(globalThis.fetch).not.toHaveBeenCalled()
})

test('does not render when the platform has no cheat surface', () => {
  mockFetch(PAYLOAD)
  const { container } = render(<PcCheatsPanel gameUuid="abc" cheatSurface="none" />)
  expect(container).toBeEmptyDOMElement()
})

test('lists cheat notes on a PC title', async () => {
  mockFetch(PAYLOAD)
  render(<PcCheatsPanel gameUuid="abc" cheatSurface="pc_wand" />)

  expect(await screen.findByText('God mode')).toBeInTheDocument()
  expect(screen.getByText('sv_cheats 1; god')).toBeInTheDocument()
  expect(screen.getByText('In-game console command')).toBeInTheDocument()
  expect(screen.getByText('Open console with ~')).toBeInTheDocument()
})

test('states the notes-not-a-trainer stance', async () => {
  mockFetch(PAYLOAD)
  render(<PcCheatsPanel gameUuid="abc" cheatSurface="pc_wand" />)
  expect(await screen.findByText(/never modifies game files/i)).toBeInTheDocument()
})

test('flags single-player entries', async () => {
  mockFetch(PAYLOAD)
  render(<PcCheatsPanel gameUuid="abc" cheatSurface="pc_wand" />)
  expect(await screen.findByText('single-player')).toBeInTheDocument()
})

test('honest empty state rather than a blank panel', async () => {
  mockFetch({ ok: true, cheats: [], methods: [], stance: '' })
  render(<PcCheatsPanel gameUuid="abc" cheatSurface="pc_wand" />)
  expect(await screen.findByText(/No cheats recorded/i)).toBeInTheDocument()
})

test('surfaces a load failure instead of showing nothing', async () => {
  mockFetch({ error: 'Nope' }, false)
  render(<PcCheatsPanel gameUuid="abc" cheatSurface="pc_wand" />)
  await waitFor(() => {
    expect(screen.getByRole('alert')).toHaveTextContent('Nope')
  })
})
