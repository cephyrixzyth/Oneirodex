import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { confirmAction } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { NewsletterPage } from './NewsletterPage'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (original) => ({ ...(await original()), confirmAction: vi.fn() }))
afterEach(() => vi.resetAllMocks())
const state = {
  newsletter_enabled: true,
  smtp_ready: true,
  can_send: true,
  recipients: [
    { id: 1, email: 'one@example.test' },
    { id: 2, email: 'two@example.test' },
  ],
  newsletters: [
    { id: 7, subject: 'Queued review', sent_date: null, status: 'pending', recipient_count: 2 },
    {
      id: 8,
      subject: 'Failed review',
      sent_date: '2026-01-01',
      status: 'failed',
      recipient_count: 1,
    },
  ],
}
function mount(path = '/admin/newsletter') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin/newsletter" element={<NewsletterPage />} />
        <Route path="/admin/newsletter/:newsletterId" element={<NewsletterPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

test('prerequisites disable compose but history and correct settings links remain', async () => {
  vi.mocked(getJson).mockResolvedValue({
    ...state,
    can_send: false,
    newsletter_enabled: false,
    smtp_ready: false,
  })
  mount()
  expect(await screen.findByText('Newsletter sending is not ready.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Server settings' })).toHaveAttribute(
    'href',
    '/admin/new_server_settings',
  )
  expect(screen.getByRole('link', { name: 'SMTP settings' })).toHaveAttribute(
    'href',
    '/admin/smtp_settings',
  )
  expect(screen.getByLabelText('Subject')).toBeDisabled()
  expect(screen.getByText('Pending')).toBeInTheDocument()
  expect(screen.getByText('Failed')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Newsletter history table' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'View Queued review' })).toHaveAttribute(
    'href',
    '/admin/newsletter/7',
  )
})

test('all/none selection, confirmation cancel and failed send retain drafts', async () => {
  vi.mocked(getJson).mockResolvedValue(state)
  vi.mocked(confirmAction).mockResolvedValueOnce(false).mockResolvedValueOnce(true)
  vi.mocked(postJson).mockRejectedValue(new Error('Delivery unavailable'))
  mount()
  const subject = await screen.findByLabelText('Subject')
  fireEvent.change(subject, { target: { value: 'Draft' } })
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Message draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'Select no recipients' }))
  expect(screen.getByRole('button', { name: 'Send newsletter' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Select all recipients' }))
  fireEvent.click(screen.getByLabelText('two@example.test'))
  const send = screen.getByRole('button', { name: 'Send newsletter' })
  fireEvent.click(send)
  await waitFor(() => expect(confirmAction).toHaveBeenCalledTimes(1))
  expect(postJson).not.toHaveBeenCalled()
  fireEvent.click(send)
  expect(await screen.findByRole('alert')).toHaveTextContent('Delivery unavailable')
  expect(subject).toHaveValue('Draft')
  expect(screen.getByLabelText('Message')).toHaveValue('Message draft')
  expect(postJson).toHaveBeenCalledWith('/api/admin/newsletters', {
    subject: 'Draft',
    content: 'Message draft',
    recipients: ['one@example.test'],
  })
})

test.each(['sent', 'failed', 'pending'])(
  'successful action reports truthful %s and adds history without a risky retry fetch',
  async (status) => {
    vi.mocked(getJson).mockResolvedValue(state)
    vi.mocked(confirmAction).mockResolvedValue(true)
    vi.mocked(postJson).mockResolvedValue({
      newsletter: {
        id: 9,
        subject: 'Fresh',
        content: 'Text',
        status,
        recipient_count: 2,
        sent_date: null,
      },
      failed_count: status === 'failed' ? 1 : 0,
    })
    mount()
    fireEvent.change(await screen.findByLabelText('Subject'), { target: { value: 'Fresh' } })
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Text' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send newsletter' }))
    expect(await screen.findByRole('link', { name: 'View Fresh' })).toHaveAttribute(
      'href',
      '/admin/newsletter/9',
    )
    expect(screen.getByLabelText('Subject')).toHaveValue(status === 'sent' ? '' : 'Fresh')
    expect(getJson).toHaveBeenCalledTimes(1)
  },
)

test('load retry and escaped plain-text detail preserve line breaks without markup execution', async () => {
  vi.mocked(getJson)
    .mockRejectedValueOnce(new Error('History unavailable'))
    .mockResolvedValue({
      newsletter: {
        ...state.newsletters[0],
        sender: 'Reviewer',
        content: '<img src=x onerror=alert(1)>\nSecond line',
        delivery_error: null,
      },
    })
  const { container } = mount('/admin/newsletter/7')
  expect(await screen.findByRole('alert')).toHaveTextContent('History unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading newsletters' }))
  const content = await screen.findByLabelText('Newsletter message')
  expect(content.textContent).toBe('<img src=x onerror=alert(1)>\nSecond line')
  expect(container.querySelector('img')).toBeNull()
  expect(screen.getByRole('link', { name: 'Back to newsletters' })).toHaveAttribute(
    'href',
    '/admin/newsletter',
  )
  expect(getJson).toHaveBeenLastCalledWith('/api/admin/newsletters/7')
})
