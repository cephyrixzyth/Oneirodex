import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { LibraryRoom } from './LibraryRoom'
import { wrapReadingText } from './roomReading'
import type { RoomAction, RoomView } from './roomScene'

const room = vi.hoisted(() => ({
  move: vi.fn(),
  update: vi.fn<(view: RoomView) => void>(),
  dispose: vi.fn(),
  enter: vi.fn(),
  exit: vi.fn(),
  theme: '',
}))
let choose: RoomAction
vi.mock('./roomScene', () => ({
  createRoom: (
    _: HTMLCanvasElement,
    select: RoomAction,
    _xr: unknown,
    _error: unknown,
    options: { theme?: string },
  ) => {
    choose = select
    room.theme = options.theme || ''
    return room
  },
}))
afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})
const fixtures = Array.from({ length: 48 }, (_, i) => ({ uuid: 'test-' + i, name: 'Game ' + i }))
const props = {
  scope: '',
  onScope: vi.fn(),
  onFavorites: vi.fn(),
  games: fixtures,
  page: 1,
  pages: 2,
  pageSize: 48,
  total: 49,
  ready: true,
  error: false,
  selected: null,
  detailMessage: '',
  onSelect: vi.fn(),
  onPage: vi.fn(),
  onFavorite: vi.fn(),
  favoriteMessage: '',
}

test('room opens on demand and shares navigation, favorite and title selection with the catalog', async () => {
  const user = userEvent.setup()
  render(<LibraryRoom {...props} />)
  expect(room.update).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Open room' }))
  await screen.findByRole('group', { name: 'Room stations' })
  expect(room.update.mock.lastCall?.[0].games).toEqual(fixtures.slice(0, 4))
  act(() => choose('@next'))
  expect(room.update.mock.lastCall?.[0].games).toEqual(fixtures.slice(4, 8))
  act(() => choose('test-4'))
  expect(props.onSelect).toHaveBeenCalledWith('test-4')
  act(() => choose('@favorite'))
  expect(props.onFavorite).toHaveBeenCalledOnce()
  act(() => choose('@scope'))
  expect(props.onScope).toHaveBeenCalledOnce()
  act(() => choose('@favorites'))
  expect(props.onFavorites).toHaveBeenCalledOnce()
  expect(room.move).toHaveBeenCalledWith('library')
  await user.click(screen.getByRole('button', { name: 'Close room' }))
  expect(room.dispose).toHaveBeenCalledOnce()
  expect(screen.getByRole('button', { name: 'Open room' })).toHaveFocus()
})
test('last server page and unavailable headset keep the desktop shelf navigable', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('navigator', { ...navigator, xr: { isSessionSupported: async () => true } })
  room.enter.mockRejectedValueOnce(new Error('session refused'))
  render(<LibraryRoom {...props} initiallyOpen page={2} games={fixtures.slice(0, 1)} />)
  expect(await screen.findByText('Titles 49–49 of 49')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Next shelf' })).toBeDisabled()
  await user.click(await screen.findByRole('button', { name: 'Enter headset' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('headset session could not start')
  expect(room.dispose).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Previous shelf' }))
  expect(props.onPage).toHaveBeenCalledWith(1)
})
test('long titles and unspaced scripts wrap across pages without discarding text', () => {
  const text = '大星図宇宙探索天文館 a longwordexample'
  const lines = wrapReadingText(text, 5, (s) => [...s].length)
  expect(lines.every((line) => [...line].length <= 5)).toBe(true)
  expect(lines.join('').replaceAll(' ', '')).toBe(text.replaceAll(' ', ''))
})

test('visits last only until closing the room', async () => {
  const user = userEvent.setup()
  render(<LibraryRoom {...props} />)
  await user.click(screen.getByRole('button', { name: 'Open room' }))
  const selector = await screen.findByLabelText('Visit room')
  await user.selectOptions(selector, 'oneirodex')
  await user.click(screen.getByRole('button', { name: 'Close room' }))
  await user.click(screen.getByRole('button', { name: 'Open room' }))
  expect(await screen.findByLabelText('Visit room')).toHaveValue('')
})

test('follows account theme changes while an explicit visit remains independent', async () => {
  document.documentElement.dataset.theme = 'default'
  const user = userEvent.setup()
  const { unmount } = render(<LibraryRoom {...props} initiallyOpen />)
  await screen.findByLabelText('Visit room')
  act(() => {
    document.documentElement.dataset.theme = 'afterglow'
  })
  await waitFor(() => expect(room.theme).toBe('afterglow'))
  await user.selectOptions(screen.getByLabelText('Visit room'), 'oneirodex')
  await waitFor(() => expect(room.theme).toBe('oneirodex'))
  act(() => {
    document.documentElement.dataset.theme = 'tideglass'
  })
  await waitFor(() => expect(room.theme).toBe('oneirodex'))
  unmount()
  delete document.documentElement.dataset.theme
})
