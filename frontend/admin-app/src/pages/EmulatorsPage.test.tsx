import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EmulatorProfilesForm, EmulatorsPage } from './EmulatorsPage'

function jsonOk(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async () => JSON.stringify(body),
    json: async () => body,
  }
}

const DATA = {
  catalog: { NES: ['nestopia', 'fceumm'], SNES: ['snes9x'] },
  profiles: { NES: 'fceumm', SNES: null },
}

describe('EmulatorProfilesForm', () => {
  const originalFetch = globalThis.fetch
  let puts: any[]

  beforeEach(() => {
    puts = []
    globalThis.fetch = vi.fn(async (url: any, init: any) => {
      const method = (init?.method || 'GET').toUpperCase()
      if (!String(url).includes('/api/emulator-profiles'))
        throw new Error(`unexpected fetch ${url}`)
      if (method === 'GET') return jsonOk(DATA)
      const body = JSON.parse(init.body)
      puts.push(body)
      return jsonOk({ catalog: DATA.catalog, profiles: body.profiles })
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  test('renders one select per catalogued platform with the preferred core selected', async () => {
    render(<EmulatorProfilesForm />)
    const nes = (await screen.findByLabelText('NES')) as HTMLSelectElement
    expect(nes.value).toBe('fceumm')
    const snes = screen.getByLabelText('SNES') as HTMLSelectElement
    expect(snes.value).toBe('')
    expect(snes.options[0].textContent).toBe('Default (first core)')
  })

  test('save PUTs every platform, null for the default', async () => {
    const user = userEvent.setup()
    render(<EmulatorProfilesForm />)
    await screen.findByLabelText('NES')
    await user.selectOptions(screen.getByLabelText('NES'), '')
    await user.selectOptions(screen.getByLabelText('SNES'), 'snes9x')
    await user.click(screen.getByRole('button', { name: 'Save profiles' }))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(puts).toEqual([{ profiles: { NES: null, SNES: 'snes9x' } }])
  })

  test('an empty catalogue says so', async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonOk({ catalog: {}, profiles: {} }),
    ) as unknown as typeof fetch
    render(<EmulatorProfilesForm />)
    expect(await screen.findByText('No emulator platforms available.')).toBeInTheDocument()
  })
})

describe('EmulatorsPage navigation', () => {
  test('keeps the long settings panels behind compact accessible tabs', () => {
    render(<EmulatorsPage />)
    expect(screen.getByRole('tab', { name: 'Preferred cores' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tabpanel', { name: 'Preferred cores' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Firmware' })).toHaveAttribute('aria-selected', 'false')
  })

  test('selects the requested settings section', async () => {
    const user = userEvent.setup()
    render(<EmulatorsPage />)
    await user.click(screen.getByRole('tab', { name: 'Firmware' }))
    expect(screen.getByRole('tab', { name: 'Firmware' })).toHaveAttribute('aria-selected', 'true')
    expect(document.getElementById('emu-panel-firmware')).not.toHaveAttribute('hidden')
    expect(document.getElementById('emu-panel-cores')).toHaveAttribute('hidden')
  })
})
