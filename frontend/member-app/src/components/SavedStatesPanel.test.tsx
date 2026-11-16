import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import * as savesApi from '../api/saves'
import { SavedStatesPanel } from './SavedStatesPanel'

vi.mock('../api/saves', async () => {
  const actual = await vi.importActual('../api/saves')
  return {
    ...actual,
    fetchSavedStates: vi.fn(),
    deleteSavedState: vi.fn(),
  }
})

vi.mock('../utils/toast', () => ({
  showToast: vi.fn(),
}))

const GAME_UUID = '11111111-1111-4111-8111-111111111111'
const PLAY = '/static/vendor/webretro/webretro.html?guid=abc&core=fceumm'

beforeEach(() => {
  vi.mocked(savesApi.fetchSavedStates).mockReset()
  vi.mocked(savesApi.deleteSavedState).mockReset()
})

test('does not mount for a title that cannot be played in the browser', () => {
  const { container } = render(<SavedStatesPanel gameUuid={GAME_UUID} playHref={null} />)
  expect(container).toBeEmptyDOMElement()
  expect(savesApi.fetchSavedStates).not.toHaveBeenCalled()
})

test('lists states newest first with a Resume that carries the slot', async () => {
  vi.mocked(savesApi.fetchSavedStates).mockResolvedValue({
    enabled: true,
    canWrite: true,
    canDelete: true,
    states: [
      {
        id: 1,
        game_uuid: 'g-1',
        filename: 'auto.state',
        size_bytes: 1024,
        encrypted: false,
        revision: 1,
        slot_name: 'auto',
        updated_at: new Date(Date.now() - 3 * 60000).toISOString(),
        is_state: true,
      },
      {
        id: 2,
        game_uuid: 'g-1',
        filename: 'qs-before-boss.state',
        size_bytes: 2048,
        encrypted: false,
        revision: 1,
        slot_name: 'qs-before-boss',
        updated_at: new Date(Date.now() - 2 * 3600000).toISOString(),
        is_state: true,
      },
    ],
  })
  render(<SavedStatesPanel gameUuid={GAME_UUID} playHref={PLAY} />)
  const rows = await screen.findAllByRole('listitem')
  expect(rows).toHaveLength(2)
  expect(rows[0]).toHaveTextContent('Where you left off')
  expect(rows[0]).toHaveTextContent('3 min ago')
  expect(rows[1]).toHaveTextContent('before boss')
  const resume = screen.getByRole('link', { name: 'Resume Where you left off' })
  expect(resume.getAttribute('href')).toContain('resume=auto')
  expect(resume.getAttribute('href')).toContain('guid=abc')
})

test('delete removes the row through the API', async () => {
  vi.mocked(savesApi.fetchSavedStates)
    .mockResolvedValueOnce({
      enabled: true,
      canWrite: true,
      canDelete: true,
      states: [
        {
          id: 3,
          game_uuid: 'g-1',
          filename: 'qs-lab.state',
          size_bytes: 512,
          encrypted: false,
          revision: 1,
          slot_name: 'qs-lab',
          updated_at: new Date().toISOString(),
          is_state: true,
        },
      ],
    })
    .mockResolvedValueOnce({ enabled: true, canWrite: true, canDelete: true, states: [] })
  vi.mocked(savesApi.deleteSavedState).mockResolvedValue({ status: 'deleted', slot_name: 'qs-lab' })
  render(<SavedStatesPanel gameUuid={GAME_UUID} playHref={PLAY} />)
  const del = await screen.findByRole('button', { name: 'Delete lab' })
  await userEvent.click(del)
  await waitFor(() => {
    expect(savesApi.deleteSavedState).toHaveBeenCalledWith(GAME_UUID, 'qs-lab')
  })
  expect(await screen.findByText(/None yet/)).toBeInTheDocument()
})

test('says so when sync is off on the server', async () => {
  vi.mocked(savesApi.fetchSavedStates).mockResolvedValue({
    enabled: false,
    canWrite: false,
    canDelete: false,
    states: [],
  })
  render(<SavedStatesPanel gameUuid={GAME_UUID} playHref={PLAY} />)
  expect(await screen.findByText(/Save sync is off/)).toBeInTheDocument()
})
