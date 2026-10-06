import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { ShellConfigProvider } from '@oneirodex/ui'
import { VrPage } from './VrPage'

afterEach(() => vi.unstubAllGlobals())

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
