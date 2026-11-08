import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Button, Modal, PageStatus, RailIcon } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import '../components/OpenPathModal.css'

interface SmtpForm {
  smtp_enabled: boolean
  smtp_server: string
  smtp_port: string
  smtp_username: string
  smtp_password: string
  smtp_use_tls: boolean
  smtp_default_sender: string
}
const EMPTY: SmtpForm = {
  smtp_enabled: false,
  smtp_server: '',
  smtp_port: '587',
  smtp_username: '',
  smtp_password: '',
  smtp_use_tls: true,
  smtp_default_sender: '',
}
function formFrom(data: Partial<SmtpForm>): SmtpForm {
  return {
    smtp_enabled: Boolean(data.smtp_enabled),
    smtp_server: data.smtp_server || '',
    smtp_port: String(data.smtp_port ?? 587),
    smtp_username: data.smtp_username || '',
    smtp_password: '',
    smtp_use_tls: data.smtp_use_tls !== false,
    smtp_default_sender: data.smtp_default_sender || '',
  }
}

export function SmtpPage() {
  const helpTitleId = useId()
  const helpTriggerRef = useRef<HTMLButtonElement | null>(null)
  const helpCloseRef = useRef<HTMLButtonElement | null>(null)
  const [form, setForm] = useState(EMPTY)
  const [passwordSaved, setPasswordSaved] = useState(false)
  const [lastTested, setLastTested] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [helpOpen, setHelpOpen] = useState(false)
  function accept(
    data: Partial<SmtpForm> & { password_saved?: boolean; last_tested?: string | null },
  ) {
    const next = formFrom(data)
    setForm(next)
    setPasswordSaved(Boolean(data.password_saved))
    setLastTested(data.last_tested || null)
  }
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    setError('')
    getJson('/api/admin/smtp/settings')
      .then((data) => {
        if (!cancelled) accept(data.settings)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err))
          setFailed(true)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reload])
  function field<K extends keyof SmtpForm>(key: K, value: SmtpForm[K]) {
    setForm((previous) => ({ ...previous, [key]: value }))
    setError('')
    setMessage('')
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (loading || failed || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await postJson('/admin/smtp_settings', form)
      if (data.status !== 'success')
        throw new Error(data.message || 'Could not save SMTP settings.')
      setForm({ ...form, smtp_password: '' })
      setPasswordSaved(passwordSaved || Boolean(form.smtp_password))
      setMessage('SMTP settings saved successfully')
    } catch (err) {
      const text = `Error saving SMTP settings: ${errorText(err) || 'Unknown error'}`
      setError(text)
    } finally {
      setBusy(false)
    }
  }
  async function testConnection() {
    if (busy || loading || failed) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await postJson('/admin/smtp_test')
      if (!data.success) {
        const text = data.message || 'SMTP connection failed.'
        setError(`SMTP connection failed: ${text}`)
        return
      }
      setMessage('SMTP connection successful. No email was sent.')
    } catch (err) {
      const text = `Error testing SMTP connection: ${errorText(err) || 'Unknown error'}`
      setError(text)
    } finally {
      setBusy(false)
    }
  }
  const disabled = loading || failed || busy
  return (
    <Page
      title="SMTP Settings"
      documentTitle="SMTP"
      lede="Configure outgoing email for account messages and invitations."
    >
      <PageStatus error={error || null} />
      {message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      {failed ? (
        <Button onClick={() => setReload((value) => value + 1)}>Retry loading settings</Button>
      ) : null}
      {loading ? (
        <PageStatus loading loadingMessage="Loading SMTP settings…" />
      ) : (
        <form className="od-admin-panel" noValidate onSubmit={save}>
          <div className="od-admin-panel__toolbar od-admin-panel__toolbar--row">
            <h2 className="od-admin-panel-title">SMTP Settings</h2>
            <Button
              ref={helpTriggerRef}
              variant="quiet"
              size="sm"
              aria-label="SMTP help"
              aria-haspopup="dialog"
              aria-expanded={helpOpen}
              title="SMTP help"
              onClick={() => setHelpOpen(true)}
            >
              <RailIcon name="help" size={16} aria-hidden="true" focusable="false" />
            </Button>
          </div>
          <p className="od-admin-hint">
            Save changes before testing. The test checks the saved connection and authentication
            without sending email.
          </p>
          <div className="od-admin-actions od-smtp-actions">
            <Button type="submit" variant="primary" disabled={disabled}>
              {busy ? 'Working…' : 'Save Settings'}
            </Button>
            <Button disabled={disabled} onClick={testConnection}>
              Test Settings
            </Button>
          </div>
          {lastTested ? <p className="od-admin-hint">Last tested: {lastTested}</p> : null}
          <fieldset className="od-admin-panel" disabled={disabled}>
            <legend>Connection settings</legend>
            <label className="od-admin-field">
              <input
                id="smtp_enabled"
                type="checkbox"
                checked={form.smtp_enabled}
                onChange={(e) => field('smtp_enabled', e.target.checked)}
              />{' '}
              Enable SMTP
            </label>
            <label className="od-admin-field">
              SMTP Server <span aria-hidden="true">*</span>
              <input
                className="od-admin-input"
                id="smtp_server"
                required
                value={form.smtp_server}
                onChange={(e) => field('smtp_server', e.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Port
              <input
                className="od-admin-input"
                id="smtp_port"
                type="number"
                step={1}
                value={form.smtp_port}
                onChange={(e) => field('smtp_port', e.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Username
              <input
                className="od-admin-input"
                id="smtp_username"
                autoComplete="off"
                value={form.smtp_username}
                onChange={(e) => field('smtp_username', e.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Password
              <input
                className="od-admin-input"
                id="smtp_password"
                type="password"
                autoComplete="new-password"
                aria-describedby="smtp-password-help"
                value={form.smtp_password}
                onChange={(e) => field('smtp_password', e.target.value)}
              />
            </label>
            <p id="smtp-password-help" className="od-admin-hint">
              {passwordSaved
                ? 'A password is saved. Leave blank to keep it.'
                : 'No password is saved.'}
            </p>
            <label className="od-admin-field">
              <input
                id="smtp_use_tls"
                type="checkbox"
                checked={form.smtp_use_tls}
                aria-describedby="smtp-tls-help"
                onChange={(e) => field('smtp_use_tls', e.target.checked)}
              />{' '}
              Use TLS
            </label>
            <p id="smtp-tls-help" className="od-admin-hint">
              Port 465 uses implicit TLS and requires this setting. Other TLS-enabled ports use
              STARTTLS.
            </p>
            <label className="od-admin-field">
              Default Sender Email
              <input
                className="od-admin-input"
                id="smtp_default_sender"
                type="email"
                value={form.smtp_default_sender}
                onChange={(e) => field('smtp_default_sender', e.target.value)}
              />
            </label>
          </fieldset>
        </form>
      )}
      <Modal
        open={helpOpen}
        onClose={() => setHelpOpen(false)}
        labelledBy={helpTitleId}
        className="od-open-path"
        panelClassName="od-open-path__panel"
        initialFocusRef={helpCloseRef}
        restoreFocusRef={helpTriggerRef}
        lockScroll
      >
        <div className="od-open-path__toolbar">
          <h2 id={helpTitleId} className="od-open-path__title">
            How to Get SMTP Server Information
          </h2>
          <button
            ref={helpCloseRef}
            type="button"
            className="od-open-path__close"
            onClick={() => setHelpOpen(false)}
            aria-label="Close SMTP help"
          >
            ×
          </button>
        </div>
        <section aria-labelledby={`${helpTitleId}-isp`}>
          <h3 id={`${helpTitleId}-isp`}>
            Option 1: Use Your Internet Service Provider’s SMTP Server (Recommended)
          </h3>
          <p>
            Most Internet Service Providers (ISPs) provide SMTP server access. This is typically the
            most reliable option for most users.
          </p>
          <ul>
            <li>Check your ISP’s support website or documentation</li>
            <li>Contact your ISP’s customer support</li>
            <li>
              Common format: <code>smtp.yourisp.com</code>
            </li>
          </ul>
        </section>
        <section aria-labelledby={`${helpTitleId}-gmail`}>
          <h3 id={`${helpTitleId}-gmail`}>Option 2: Use Gmail SMTP</h3>
          <p>Gmail provides SMTP access, but may require additional account setup:</p>
          <ul>
            <li>
              Server: <code>smtp.gmail.com</code>
            </li>
            <li>
              Port: <code>587</code>
            </li>
            <li>Security: TLS</li>
            <li>
              If your account requires an app password, follow Google’s current account-security
              instructions.
            </li>
          </ul>
        </section>
        <section aria-labelledby={`${helpTitleId}-professional`}>
          <h3 id={`${helpTitleId}-professional`}>Option 3: Use Professional SMTP Services</h3>
          <p>These services offer reliable email delivery with higher limits:</p>
          <ul>
            <li>SendGrid</li>
            <li>Amazon Simple Email Service</li>
            <li>Mailgun</li>
            <li>SMTP2GO</li>
          </ul>
        </section>
        <p className="od-open-path__reason">
          Always use TLS when available, and verify the port with your provider. Testing checks
          connection and authentication only; it does not send email or confirm delivery.
        </p>
        <div className="od-open-path__actions">
          <Button onClick={() => setHelpOpen(false)}>Close</Button>
        </div>
      </Modal>
    </Page>
  )
}
