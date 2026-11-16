import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { AttractModePage } from './AttractModePage'
import { getJson, putJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const settings = {
  enabled: false,
  idle_timeout: 60,
  filters: { library_uuid: null, genres: [1], themes: [], date_from: 2000, date_to: null },
  autoplay: { enabled: true, skipFirst: 5, skipAfter: 30 },
}
const response = {
  settings,
  filter_options: {
    libraries: [{ uuid: 'review-library', name: 'Review library' }],
    genres: [{ id: 1, name: 'Review genre' }],
    themes: [],
  },
}

test('loads disabled configuration and saves all filters and autoplay settings', async () => {
  vi.mocked(getJson).mockResolvedValue(response)
  vi.mocked(putJson).mockResolvedValue({ settings: { ...settings, idle_timeout: 70 } })
  render(<AttractModePage />)
  const timeout = await screen.findByLabelText('Idle timeout (seconds)')
  expect(screen.getByLabelText('Enable attract mode')).not.toBeChecked()
  expect(screen.getByLabelText('Genres', { exact: false })).toHaveValue(['1'])
  expect(screen.getByLabelText('Skip first (seconds)')).toHaveValue(5)
  fireEvent.change(timeout, { target: { value: '70' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('Attract mode settings saved successfully')).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith('/api/admin/attract-mode/settings', {
    ...settings,
    idle_timeout: 70,
  })
})

test('failed load disables default saves and retry restores config', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Config unavailable'))
    .mockResolvedValueOnce(response)
  render(<AttractModePage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Config unavailable')
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading settings' }))
  expect(await screen.findByLabelText('Idle timeout (seconds)')).toHaveValue(60)
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeEnabled()
})

test('failed save retains draft and preview', async () => {
  vi.mocked(getJson).mockResolvedValue(response)
  vi.mocked(putJson).mockRejectedValue(new Error('Invalid year range'))
  render(<AttractModePage />)
  const timeout = await screen.findByLabelText('Idle timeout (seconds)')
  fireEvent.change(timeout, { target: { value: '80' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid year range')
  expect(timeout).toHaveValue(80)
  expect(screen.getByText('Attract mode is disabled.')).toBeInTheDocument()
})
