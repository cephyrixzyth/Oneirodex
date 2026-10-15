import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { PluginsPage } from './PluginsPage'
import { getJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())

test('registry uses a captioned, named table and retains sorting/filtering', async () => {
  vi.mocked(getJson).mockResolvedValue({
    plugins: [
      { id: 'review-b', name: 'Review metadata', category: 'metadata', status: 'ready' },
      { id: 'review-a', name: 'Review export', category: 'export', status: 'built-in' },
    ],
  })
  render(<PluginsPage />)
  const table = await screen.findByRole('table', { name: 'Registered plugins and connectors' })
  expect(table).toBeInTheDocument()
  const region = screen.getByRole('region', { name: 'Plugins and connectors table' })
  expect(region).toHaveAttribute('tabindex', '0')
  expect(table.querySelector('tbody tr')).toHaveTextContent('Review export')
  fireEvent.change(screen.getByRole('searchbox', { name: 'Filter table rows' }), {
    target: { value: 'metadata' },
  })
  expect(screen.queryByText('Review export')).not.toBeInTheDocument()
  expect(screen.getByText('Review metadata')).toBeInTheDocument()
})

test('failure stops loading and retry recovers real empty state', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Registry unavailable'))
    .mockResolvedValueOnce({ plugins: [] })
  render(<PluginsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load plugins.')
  expect(document.querySelector('[aria-busy="true"]')).toBeNull()
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading plugins' }))
  expect(await screen.findByText('No plugins registered.')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('malformed response does not pretend registry is empty', async () => {
  vi.mocked(getJson).mockResolvedValue({ plugins: 'bad' })
  render(<PluginsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load plugins.')
  expect(screen.queryByText('No plugins registered.')).not.toBeInTheDocument()
})

test('unmount aborts the pending registry fetch', () => {
  vi.mocked(getJson).mockImplementation(() => new Promise(() => {}))
  const { unmount } = render(<PluginsPage />)
  const options = vi.mocked(getJson).mock.calls[0][1]
  expect(options?.signal?.aborted).toBe(false)
  unmount()
  expect(options?.signal?.aborted).toBe(true)
})
