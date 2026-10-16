import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { SmtpPage } from './SmtpPage'
import { getJson, putJson, postJson } from '../api/adminApi'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn(), postJson: vi.fn() }))
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

test('loads safe settings, saves blank password, and tests only saved connection', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: state })
  vi.mocked(putJson).mockResolvedValue({ settings: { ...state, smtp_port: 2525 } })
  vi.mocked(postJson).mockResolvedValue({ ok: true })
  render(<SmtpPage />)
  const port = await screen.findByLabelText('Port')
  expect(screen.getByLabelText('Password')).toHaveValue('')
  fireEvent.change(port, { target: { value: '2525' } })
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('SMTP settings saved.')).toBeInTheDocument()
  expect(putJson).toHaveBeenCalledWith(
    '/api/admin/smtp/settings',
    expect.objectContaining({ smtp_password: '', smtp_port: '2525' }),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(
    await screen.findByText('SMTP connection successful. No email was sent.'),
  ).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/api/admin/smtp/test')
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
  vi.mocked(putJson).mockRejectedValue(new Error('Could not save SMTP settings'))
  render(<SmtpPage />)
  const password = await screen.findByLabelText('Password')
  fireEvent.change(password, { target: { value: 'draft-test-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save SMTP settings')
  expect(password).toHaveValue('draft-test-password')
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled()
})

test('disabled SMTP cannot test, and help remains available', async () => {
  vi.mocked(getJson).mockResolvedValue({ settings: { ...state, smtp_enabled: false } })
  render(<SmtpPage />)
  await screen.findByLabelText('SMTP server')
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled()
  expect(screen.getByText('SMTP setup help')).toBeInTheDocument()
  expect(postJson).not.toHaveBeenCalled()
})
