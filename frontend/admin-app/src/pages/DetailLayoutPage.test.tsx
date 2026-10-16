import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DetailLayoutPage } from './DetailLayoutPage'

function jsonOk(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async () => JSON.stringify(body),
    json: async () => body,
  }
}

const DEFAULT = {
  sections: [
    { id: 'summary', visible: true },
    { id: 'media', visible: true },
    { id: 'facts', visible: true },
  ],
}

describe('DetailLayoutPage', () => {
  const originalFetch = globalThis.fetch
  let puts: unknown[]

  beforeEach(() => {
    puts = []
    globalThis.fetch = vi.fn(async (url: any, init: any) => {
      const method = (init?.method || 'GET').toUpperCase()
      if (!String(url).includes('/api/layouts/detail')) throw new Error(`unexpected fetch ${url}`)
      if (method === 'GET') return jsonOk(DEFAULT)
      const body = JSON.parse(init.body)
      puts.push(body)
      // The server answers with the effective layout: the sent order, or the
      // default when the list is empty (that is how Reset works).
      return jsonOk(body.sections.length ? { sections: body.sections } : DEFAULT)
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  test('lists sections in order and moves one down', async () => {
    const user = userEvent.setup()
    render(<DetailLayoutPage />)
    const list = await screen.findByRole('list', { name: 'Detail page sections' })
    const ids = () =>
      within(list)
        .getAllByRole('listitem')
        .map((li) => li.querySelector('strong')!.textContent)
    expect(ids()).toEqual(['summary', 'media', 'facts'])
    expect(screen.getByRole('button', { name: 'Move summary up' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move facts down' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Move summary down' }))
    expect(ids()).toEqual(['media', 'summary', 'facts'])
  })

  test('save PUTs the edited order and visibility', async () => {
    const user = userEvent.setup()
    render(<DetailLayoutPage />)
    await screen.findByRole('list', { name: 'Detail page sections' })

    await user.click(screen.getByRole('button', { name: 'Move facts up' }))
    const mediaRow = screen.getByText('media').closest('li')!
    await user.click(within(mediaRow).getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(puts).toEqual([
      {
        sections: [
          { id: 'summary', visible: true },
          { id: 'facts', visible: true },
          { id: 'media', visible: false },
        ],
      },
    ])
  })

  test('reset PUTs an empty list and shows the default again', async () => {
    const user = userEvent.setup()
    render(<DetailLayoutPage />)
    await screen.findByRole('list', { name: 'Detail page sections' })
    await user.click(screen.getByRole('button', { name: 'Move summary down' }))
    await user.click(screen.getByRole('button', { name: 'Reset defaults' }))

    expect(await screen.findByText('Reset')).toBeInTheDocument()
    expect(puts).toEqual([{ sections: [] }])
    const list = screen.getByRole('list', { name: 'Detail page sections' })
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((li) => li.querySelector('strong')!.textContent),
    ).toEqual(['summary', 'media', 'facts'])
  })

  test('a failed load offers retry', async () => {
    globalThis.fetch = vi.fn(async () => jsonOk({ error: 'nope' }, 500)) as unknown as typeof fetch
    render(<DetailLayoutPage />)
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  test('failed save keeps the draft and blocks changes while saving', async () => {
    const user = userEvent.setup()
    let resolveSave!: (value: any) => void
    globalThis.fetch = vi.fn(async (_url, init) =>
      init?.method === 'PUT'
        ? new Promise((resolve) => {
            resolveSave = resolve
          })
        : jsonOk(DEFAULT),
    ) as unknown as typeof fetch
    render(<DetailLayoutPage />)
    const visible = await screen.findByRole('checkbox', { name: 'Show media' })
    await user.click(visible)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(visible).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move media up' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reset defaults' })).toBeDisabled()
    resolveSave(jsonOk({ error: 'Layout save unavailable' }, 500))
    expect(await screen.findByRole('alert')).toHaveTextContent('Layout save unavailable')
    expect(visible).not.toBeChecked()
    expect(visible).toBeEnabled()
  })

  test('malformed saved response retains the current layout', async () => {
    const user = userEvent.setup()
    globalThis.fetch = vi.fn(async (_url, init) =>
      jsonOk(init?.method === 'PUT' ? {} : DEFAULT),
    ) as unknown as typeof fetch
    render(<DetailLayoutPage />)
    await screen.findByRole('checkbox', { name: 'Show summary' })
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid response')
    expect(screen.getByRole('list', { name: 'Detail page sections' }).children).toHaveLength(3)
  })
})
