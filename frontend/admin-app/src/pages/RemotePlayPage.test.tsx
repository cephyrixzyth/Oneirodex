import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { RemotePlayPage } from './RemotePlayPage'
import { getJson, putJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())

test('shared client saves loaded settings and reports success', async () => {
  vi.mocked(getJson).mockResolvedValue({
    host_label: 'Review host',
    provider: 'wolf',
    enabled: false,
  })
  vi.mocked(putJson).mockResolvedValue({ ok: true })
  render(<RemotePlayPage />)
  const host = await screen.findByLabelText('Host label (shown to members)')
  expect(host).toHaveValue('Review host')
  fireEvent.change(host, { target: { value: 'Changed host' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('Remote play settings saved.')).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith(
    '/api/admin/remote-play/config',
    expect.objectContaining({ host_label: 'Changed host', provider: 'wolf', enabled: false }),
  )
})

test('failed load prevents saving defaults and retry restores the saved config', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Settings unavailable'))
    .mockResolvedValueOnce({ host_label: 'Saved host' })
  render(<RemotePlayPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Settings unavailable')
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading settings' }))
  expect(await screen.findByLabelText('Host label (shown to members)')).toHaveValue('Saved host')
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeEnabled()
  expect(putJson).not.toHaveBeenCalled()
})

test('failed save keeps the draft and shows the server error', async () => {
  vi.mocked(getJson).mockResolvedValue({ host_label: 'Review host' })
  vi.mocked(putJson).mockRejectedValue(new Error('LAN URL policy rejected this address.'))
  render(<RemotePlayPage />)
  const host = await screen.findByLabelText('Host label (shown to members)')
  fireEvent.change(host, { target: { value: 'Draft host' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'LAN URL policy rejected this address.',
  )
  expect(host).toHaveValue('Draft host')
})
