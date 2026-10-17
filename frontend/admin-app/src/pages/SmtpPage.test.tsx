import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { SmtpPage } from './SmtpPage'
import { getJson, postJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const state = {
  smtp_enabled: true,
  smtp_server: 'smtp.example.com',
  smtp_port: 587,
  smtp_username: 'review@example.com',
  smtp_use_tls: true,
  smtp_default_sender: 'review@example.com',
  password_saved: true,
}

test('loads safe settings, saves blank password, and tests the saved connection while edits are pending', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: state })
  vi.mocked(postJson)
    .mockResolvedValueOnce({ success: true, result: 'connected' })
    .mockResolvedValueOnce({ success: true, status: 'success', message: 'saved' })
  render(<SmtpPage />)
  const port = await screen.findByLabelText('Port')
  expect(screen.getByLabelText('Password')).toHaveValue('')
  fireEvent.change(port, { target: { value: '2525' } })
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(
    await screen.findByText('SMTP connection successful. No email was sent.'),
  ).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/admin/smtp_test')
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('SMTP settings saved successfully')).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith(
    '/admin/smtp_settings',
    expect.objectContaining({ smtp_password: '', smtp_port: '2525' }),
  )
})

test('load failure guards save and test; retry recovers', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('Settings unavailable'))
    .mockResolvedValueOnce({ settings: state })
  render(<SmtpPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Settings unavailable')
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading settings' }))
  expect(await screen.findByLabelText('SMTP server')).toHaveValue('smtp.example.com')
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeEnabled()
})

test('save failure retains draft including replacement password', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: state })
  vi.mocked(postJson).mockRejectedValue(new Error('Could not save SMTP settings'))
  render(<SmtpPage />)
  const password = await screen.findByLabelText('Password')
  fireEvent.change(password, { target: { value: 'draft-test-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Error saving SMTP settings: Could not save SMTP settings',
  )
  expect(password).toHaveValue('draft-test-password')
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeEnabled()
})

test('disabled SMTP still tests the saved configuration, and help remains available', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: { ...state, smtp_enabled: false } })
  vi.mocked(postJson).mockResolvedValue({ success: true, result: 'connected' })
  render(<SmtpPage />)
  await screen.findByLabelText('SMTP server')
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeEnabled()
  expect(screen.getByText('SMTP setup help')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(
    await screen.findByText('SMTP connection successful. No email was sent.'),
  ).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/admin/smtp_test')
})

test('legacy save posts form values without the modern API field restrictions', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: { ...state, smtp_enabled: false } })
  vi.mocked(postJson).mockResolvedValue({ status: 'success', message: 'saved' })
  render(<SmtpPage />)
  const server = await screen.findByLabelText('SMTP server')
  const sender = screen.getByLabelText('Default sender email')
  const legacyLongValue = 'x'.repeat(256)
  fireEvent.change(server, { target: { value: legacyLongValue } })
  fireEvent.change(sender, { target: { value: 'not-an-email' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('SMTP settings saved successfully')).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith(
    '/admin/smtp_settings',
    expect.objectContaining({ smtp_server: legacyLongValue, smtp_default_sender: 'not-an-email' }),
  )
})
