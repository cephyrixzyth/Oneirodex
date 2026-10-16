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

  test('pending save disables core edits and a failed save retains the selection', async () => {
    const user = userEvent.setup()
    let resolveSave!: (value: any) => void
    globalThis.fetch = vi.fn(async (_url, init) =>
      init?.method === 'PUT'
        ? new Promise((resolve) => {
            resolveSave = resolve
          })
        : jsonOk(DATA),
    ) as unknown as typeof fetch
    render(<EmulatorProfilesForm />)
    const nes = await screen.findByLabelText('NES')
    expect(nes).toHaveClass('od-admin-input')
    await user.selectOptions(nes, 'nestopia')
    await user.click(screen.getByRole('button', { name: 'Save profiles' }))
    expect(nes).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save profiles' })).toBeDisabled()
    resolveSave(jsonOk({ error: 'Profile save unavailable' }, 500))
    expect(await screen.findByRole('alert')).toHaveTextContent('Profile save unavailable')
    expect(nes).toHaveValue('nestopia')
    expect(nes).toBeEnabled()
  })

  test('invalid catalogue offers retry instead of an empty state', async () => {
    const user = userEvent.setup()
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonOk({ catalog: null }))
      .mockResolvedValueOnce(jsonOk(DATA)) as unknown as typeof fetch
    render(<EmulatorProfilesForm />)
    await user.click(await screen.findByRole('button', { name: 'Try again' }))
    expect(await screen.findByLabelText('NES')).toHaveValue('fceumm')
    expect(screen.queryByText('No emulator platforms available.')).not.toBeInTheDocument()
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

  test('keyboard navigation selects and focuses the related panel', async () => {
    const user = userEvent.setup()
    render(<EmulatorsPage />)
    const tabs = screen.getAllByRole('tab')
    tabs[0].focus()
    await user.keyboard('{End}')
    expect(tabs[3]).toHaveFocus()
    expect(tabs[3]).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Firmware' })).toBeVisible()
    await user.keyboard('{ArrowRight}')
    expect(tabs[0]).toHaveFocus()
    await user.keyboard('{ArrowLeft}')
    expect(tabs[3]).toHaveFocus()
    await user.keyboard('{Home}')
    expect(tabs[0]).toHaveFocus()
  })
})
