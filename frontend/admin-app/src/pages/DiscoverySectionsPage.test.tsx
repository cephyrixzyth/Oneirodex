import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { DiscoverySectionsPage } from './DiscoverySectionsPage'
import { getJson, postJson, putJson, deleteJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'
vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
  putJson: vi.fn(),
  deleteJson: vi.fn(),
}))
vi.mock('@oneirodex/ui', async (original) => ({ ...(await original()), confirmAction: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const seed = {
  id: 1,
  name: 'Libraries',
  section_type: 'seed',
  count: 3,
  description: '',
  is_visible: true,
  is_live: true,
  config: {},
  layout: 'shelf',
  starts_at: null,
  ends_at: null,
  pin_rank: null,
}
const custom = {
  ...seed,
  id: 2,
  name: 'Review shelf',
  section_type: 'custom',
  count: 1,
  description: 'Manual game list',
  config: { mode: 'manual', game_uuids: ['game-one'] },
}
const state = {
  sections: [seed, custom],
  libraries: [{ uuid: 'library-one', name: 'Review library' }],
  platforms: [{ id: 'NES', label: 'Nintendo' }],
  genres: [{ name: 'Review genre' }],
  max_games: 60,
}

test('keyboard order/visibility preserve builtin restrictions and Live refresh', async () => {
  vi.mocked(getJson)
    .mockResolvedValueOnce(state)
    .mockResolvedValueOnce({
      ...state,
      sections: [{ ...seed, is_visible: false, is_live: false }, custom],
    })
    .mockResolvedValueOnce(state)
  vi.mocked(postJson).mockResolvedValue({ ok: true })
  render(<DiscoverySectionsPage />)
  const checkbox = await screen.findByRole('checkbox', { name: 'Visible Libraries' })
  expect(screen.queryByRole('button', { name: 'Delete Libraries' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Move Libraries up' })).toBeDisabled()
  fireEvent.click(checkbox)
  await waitFor(() => expect(checkbox).not.toBeChecked())
  await waitFor(() => expect(checkbox).toBeEnabled())
  fireEvent.click(checkbox)
  await waitFor(() => expect(checkbox).toBeChecked())
  await waitFor(() => expect(checkbox).toBeEnabled())
  expect(within(checkbox.closest('li')!).getByText(/Live · shelf/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Move Review shelf up' }))
  expect(await screen.findByText('Shelf order saved.')).toBeInTheDocument()
  expect(postJson).toHaveBeenLastCalledWith('/admin/api/discovery_sections/order', {
    sections: [
      { id: 2, order: 0 },
      { id: 1, order: 1 },
    ],
  })
})

test('manual search adds local results and UUID/order controls stay synchronized', async () => {
  vi.mocked(getJson)
    .mockResolvedValueOnce(state)
    .mockResolvedValueOnce([{ uuid: 'game-two', name: 'Review game' }])
    .mockResolvedValueOnce(state)
  vi.mocked(postJson).mockResolvedValue({ section: custom })
  render(<DiscoverySectionsPage />)
  await screen.findByRole('button', { name: 'Edit Review shelf' })
  fireEvent.click(screen.getByRole('button', { name: 'Add shelf' }))
  const dialog = screen.getByRole('dialog', { name: 'Add discovery shelf' })
  fireEvent.change(within(dialog).getByLabelText('Shelf name'), {
    target: { value: 'Manual Review' },
  })
  fireEvent.change(within(dialog).getByLabelText('Add games'), { target: { value: 'Review game' } })
  fireEvent.keyDown(within(dialog).getByLabelText('Add games'), { key: 'Enter' })
  fireEvent.click(await screen.findByRole('button', { name: 'Add Review game' }))
  expect(within(dialog).getByLabelText('Game UUIDs')).toHaveValue('game-two')
  fireEvent.change(within(dialog).getByLabelText('Game UUIDs'), {
    target: { value: 'game-one,game-two' },
  })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Move selected Review game up' }))
  expect(within(dialog).getByLabelText('Game UUIDs')).toHaveValue('game-two\ngame-one')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save shelf' }))
  expect(await screen.findByText('Shelf saved.')).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/admin/api/discovery_sections', {
    name: 'Manual Review',
    mode: 'manual',
    game_uuids: ['game-two', 'game-one'],
  })
  expect(getJson).toHaveBeenCalledWith('/api/search?query=Review%20game')
})

test.each([
  ['library', 'library-one'],
  ['platform', 'NES'],
  ['genre', 'Review genre'],
])('filter %s preserves payload and ignores oversized manual draft', async (type, value) => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.mocked(putJson).mockResolvedValue({ section: custom })
  render(<DiscoverySectionsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Review shelf' }))
  const dialog = screen.getByRole('dialog', { name: 'Edit discovery shelf' })
  fireEvent.change(within(dialog).getByLabelText('Game UUIDs'), {
    target: { value: Array.from({ length: 61 }, (_, index) => `game-${index}`).join('\n') },
  })
  expect(within(dialog).getByRole('button', { name: 'Save shelf' })).toBeDisabled()
  fireEvent.click(within(dialog).getByLabelText('Filter', { exact: true }))
  fireEvent.change(within(dialog).getByRole('combobox', { name: 'Filter by' }), {
    target: { value: type },
  })
  expect(within(dialog).getByRole('combobox', { name: 'Filter value' })).toHaveValue(value)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save shelf' }))
  expect(await screen.findByText('Shelf saved.')).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith('/admin/api/discovery_sections/2', {
    name: 'Review shelf',
    mode: 'filter',
    filter_type: type,
    filter_value: value,
  })
})

test('schedule UTC and pin controls keep separate save/clear operations', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.mocked(putJson).mockResolvedValue({ section: custom })
  render(<DiscoverySectionsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Schedule and pin Review shelf' }))
  const dialog = screen.getByRole('dialog', { name: 'Schedule and pin Review shelf' })
  fireEvent.change(within(dialog).getByRole('combobox', { name: 'Shelf layout' }), {
    target: { value: 'hero' },
  })
  fireEvent.change(within(dialog).getByLabelText('Starts at (UTC)'), {
    target: { value: '2026-10-10T10:00' },
  })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save schedule' }))
  expect(await screen.findByText('Shelf schedule saved.')).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith('/admin/api/discovery_sections/2/schedule', {
    layout: 'hero',
    starts_at: '2026-10-10T10:00Z',
    ends_at: null,
  })
  fireEvent.change(within(dialog).getByLabelText('Pin rank'), { target: { value: '2' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save pin' }))
  expect(await screen.findByText('Shelf pin saved.')).toBeInTheDocument()
  expect(putJson).toHaveBeenLastCalledWith('/admin/api/discovery_sections/2/pin', { pin_rank: 2 })
  fireEvent.change(within(dialog).getByLabelText('Pin rank'), { target: { value: '' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save pin' }))
  await waitFor(() =>
    expect(putJson).toHaveBeenLastCalledWith('/admin/api/discovery_sections/2/pin', {
      pin_rank: null,
    }),
  )
})

test('load Retry, failed edit draft retention and confirmed custom deletion', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Sections unavailable'))
    .mockResolvedValue(state)
  vi.mocked(putJson).mockRejectedValue(new Error('Save unavailable'))
  vi.mocked(deleteJson).mockResolvedValue({ ok: true })
  vi.mocked(confirmAction).mockResolvedValueOnce(false).mockResolvedValueOnce(true)
  render(<DiscoverySectionsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Sections unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading discovery sections' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Review shelf' }))
  const name = screen.getByLabelText('Shelf name')
  fireEvent.change(name, { target: { value: 'Retained draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save shelf' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save unavailable')
  expect(name).toHaveValue('Retained draft')
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  const remove = screen.getByRole('button', { name: 'Delete Review shelf' })
  fireEvent.click(remove)
  await waitFor(() => expect(remove).toBeEnabled())
  expect(deleteJson).not.toHaveBeenCalled()
  fireEvent.click(remove)
  expect(await screen.findByText('Shelf deleted.')).toBeInTheDocument()
  expect(deleteJson).toHaveBeenCalledWith('/admin/api/discovery_sections/2')
})

test('confirmation keeps the delete opener enabled for cancel and Escape focus return', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  let close: (value: boolean) => void = () => {}
  vi.mocked(confirmAction).mockImplementation(
    () =>
      new Promise<boolean>((resolve) => {
        close = resolve
      }),
  )
  render(<DiscoverySectionsPage />)
  const opener = await screen.findByRole('button', { name: 'Delete Review shelf' })
  for (const dismiss of ['cancel', 'Escape']) {
    opener.focus()
    fireEvent.click(opener)
    await waitFor(() => expect(confirmAction).toHaveBeenCalled())
    expect(opener).toBeEnabled()
    // The shared confirmation returns focus before resolving either dismissal.
    opener.focus()
    close(false)
    await waitFor(() => expect(opener).toHaveFocus())
    expect(deleteJson).not.toHaveBeenCalled()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
})
