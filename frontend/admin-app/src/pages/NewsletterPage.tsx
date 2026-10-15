import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { DataTable } from '../components/DataTable'
import { errorText } from '../utils/errorText'
import './NewsletterPage.css'

type Entry = {
  id: number
  subject: string
  sent_date: string | null
  status: string
  recipient_count: number
  content?: string
  sender?: string
  delivery_error?: string
}
type State = {
  newsletter_enabled: boolean
  smtp_ready: boolean
  can_send: boolean
  recipients: { id: number; email: string }[]
  newsletters: Entry[]
  newsletter?: Entry
}
const API = '/api/admin/newsletters'
const statusLabel = (status: string) =>
  ({ pending: 'Pending', sent: 'Sent', failed: 'Failed' })[status] || 'Unknown'
export function NewsletterPage() {
  const { newsletterId } = useParams()
  const validId = !newsletterId || /^[0-9]+$/.test(newsletterId)
  const [data, setData] = useState<State | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadFailed, setLoadFailed] = useState(false)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [subject, setSubject] = useState('')
  const [content, setContent] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [message, setMessage] = useState('')
  const lock = useRef(false)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    setData(null)
    if (!validId) {
      setError('Newsletter not found.')
      setLoadFailed(true)
      setLoading(false)
      return
    }
    getJson(newsletterId ? `${API}/${newsletterId}` : API)
      .then((value) => {
        if (cancelled) return
        if (newsletterId) {
          if (!value?.newsletter || typeof value.newsletter !== 'object') {
            throw new Error('Newsletter detail response was incomplete.')
          }
          setData(value)
          return
        }
        if (!Array.isArray(value?.recipients) || !Array.isArray(value?.newsletters)) {
          throw new Error('Newsletter history response was incomplete.')
        }
        setData(value)
        setSelected(value.recipients.map((row: { email: string }) => row.email))
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err))
          setLoadFailed(true)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [newsletterId, reload, validId])
  async function send(event: FormEvent) {
    event.preventDefault()
    if (lock.current || !data?.can_send || loading || loadFailed) return
    lock.current = true
    setError('')
    setMessage('')
    try {
      if (
        !(await confirmAction({
          title: 'Send this newsletter?',
          body: `Send to ${selected.length} selected recipient(s)?`,
          confirmLabel: 'Send newsletter',
          cancelLabel: 'Keep draft',
        }))
      )
        return
      setBusy(true)
      const result = await postJson(API, { subject, content, recipients: selected })
      const entry: Entry = result.newsletter
      setData((current) =>
        current ? { ...current, newsletters: [entry, ...current.newsletters] } : current,
      )
      setMessage(
        entry.status === 'sent'
          ? 'Newsletter sent.'
          : entry.status === 'failed'
            ? `Newsletter delivery failed for ${result.failed_count} recipient(s). Review history before sending again.`
            : 'Delivery is pending. Review history before sending again.',
      )
      if (entry.status === 'sent') {
        setSubject('')
        setContent('')
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  const disabled = loading || loadFailed || busy || !data?.can_send
  const detail = data?.newsletter
  const recipients = Array.isArray(data?.recipients) ? data.recipients : []
  const newsletters = Array.isArray(data?.newsletters) ? data.newsletters : []
  return (
    <Page
      title={newsletterId ? detail?.subject || 'Newsletter detail' : 'Newsletter'}
      lede={
        newsletterId
          ? 'Newsletter message detail.'
          : 'Compose announcements and review delivery history.'
      }
    >
      <PageStatus loading={loading} loadingMessage="Loading newsletters..." error={error || null} />
      {loadFailed && validId ? (
        <Button disabled={loading} onClick={() => setReload((value) => value + 1)}>
          Retry loading newsletters
        </Button>
      ) : null}
      {message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      {newsletterId ? (
        <>
          {detail ? (
            <section className="od-admin-panel">
              <dl>
                <dt>Sent by</dt>
                <dd>{detail.sender}</dd>
                <dt>Date</dt>
                <dd>{detail.sent_date || '--'}</dd>
                <dt>Recipients</dt>
                <dd>{detail.recipient_count}</dd>
                <dt>Status</dt>
                <dd>{statusLabel(detail.status)}</dd>
              </dl>
              {detail.delivery_error ? (
                <PageStatus announcement="status">{detail.delivery_error}</PageStatus>
              ) : null}
              <div className="od-newsletter-message" aria-label="Newsletter message">
                {detail.content}
              </div>
            </section>
          ) : null}
          <Link to="/admin/newsletter">Back to newsletters</Link>
        </>
      ) : data ? (
        <>
          {!data.can_send ? (
            <PageStatus announcement="status" className={'od-admin-panel'}>
              <strong>Newsletter sending is not ready.</strong>
              {!data.newsletter_enabled ? (
                <p>
                  Enable newsletters in <Link to="/admin/new_server_settings">Server settings</Link>
                  .
                </p>
              ) : null}
              {!data.smtp_ready ? (
                <p>
                  Configure an enabled server and sender in{' '}
                  <Link to="/admin/smtp_settings">SMTP settings</Link>.
                </p>
              ) : null}
              <p>You can still review newsletter history.</p>
            </PageStatus>
          ) : null}
          <form onSubmit={send} className="od-admin-panel od-newsletter-compose">
            <fieldset className="od-admin-fieldset" disabled={disabled}>
              <legend>Compose newsletter</legend>
              <label className="od-admin-field">
                Subject
                <input
                  className="od-admin-input"
                  value={subject}
                  onChange={(event) => setSubject(event.target.value)}
                  maxLength={255}
                  required
                />
              </label>
              <label className="od-admin-field">
                Message
                <textarea
                  className="od-admin-input"
                  value={content}
                  onChange={(event) => setContent(event.target.value)}
                  rows={12}
                  maxLength={1048576}
                  required
                />
              </label>
              <div className="od-admin-actions-row">
                <Button
                  type="button"
                  onClick={() => setSelected([...new Set(recipients.map((row) => row.email))])}
                >
                  Select all recipients
                </Button>
                <Button type="button" onClick={() => setSelected([])}>
                  Select no recipients
                </Button>
              </div>
              <fieldset className="od-admin-fieldset">
                <legend>Recipients ({selected.length})</legend>
                {recipients.map((row) => (
                  <label className="od-admin-field" key={row.id}>
                    <input
                      type="checkbox"
                      checked={selected.includes(row.email)}
                      onChange={(event) =>
                        setSelected((current) =>
                          event.target.checked
                            ? [...new Set([...current, row.email])]
                            : current.filter((email) => email !== row.email),
                        )
                      }
                    />
                    {row.email}
                  </label>
                ))}
                {!recipients.length ? <p>No member email addresses available.</p> : null}
              </fieldset>
              <Button
                type="submit"
                disabled={disabled || !selected.length || !subject.trim() || !content.trim()}
              >
                {busy ? 'Sending...' : 'Send newsletter'}
              </Button>
            </fieldset>
          </form>
          <section className="od-admin-panel">
            <h2 className="od-newsletter-heading">Newsletter history</h2>
            <DataTable
              caption="Newsletter delivery history"
              scrollLabel="Newsletter history table"
              rows={newsletters}
              getRowKey={(row) => row.id}
              emptyMessage="No newsletters yet."
              columns={[
                { key: 'subject', label: 'Subject' },
                { key: 'sent_date', label: 'Date', render: (row) => row.sent_date || '--' },
                { key: 'status', label: 'Status', render: (row) => statusLabel(row.status) },
                { key: 'recipient_count', label: 'Recipients' },
                {
                  key: 'action',
                  label: 'Action',
                  render: (row) => (
                    <Link to={`/admin/newsletter/${row.id}`} aria-label={`View ${row.subject}`}>
                      View
                    </Link>
                  ),
                },
              ]}
            />
          </section>
        </>
      ) : null}
    </Page>
  )
}
