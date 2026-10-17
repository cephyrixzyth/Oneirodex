import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'

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
  const [form, setForm] = useState(EMPTY)
  const [passwordSaved, setPasswordSaved] = useState(false)
  const [lastTested, setLastTested] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
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
      showToast('SMTP settings saved successfully', 'success')
    } catch (err) {
      const text = `Error saving SMTP settings: ${errorText(err) || 'Unknown error'}`
      setError(text)
      showToast(text, 'error')
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
        setError(text)
        showToast(`SMTP connection failed: ${text}`, 'error')
        return
      }
      setMessage('SMTP connection successful. No email was sent.')
      showToast('SMTP connection successful', 'success')
    } catch (err) {
      const text = `Error testing SMTP connection: ${errorText(err) || 'Unknown error'}`
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy(false)
    }
  }
  const disabled = loading || failed || busy
  return (
    <Page title="SMTP" lede="Configure outgoing email for account messages and invitations.">
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
          <fieldset className="od-admin-panel" disabled={disabled}>
            <legend>Connection settings</legend>
            <label className="od-admin-field">
              <input
                type="checkbox"
                checked={form.smtp_enabled}
                onChange={(e) => field('smtp_enabled', e.target.checked)}
              />{' '}
              Enable SMTP
            </label>
            <label className="od-admin-field">
              SMTP server
              <input
                className="od-admin-input"
                value={form.smtp_server}
                onChange={(e) => field('smtp_server', e.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Port
              <input
                className="od-admin-input"
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
                autoComplete="off"
                value={form.smtp_username}
                onChange={(e) => field('smtp_username', e.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Password
              <input
                className="od-admin-input"
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
                type="checkbox"
                checked={form.smtp_use_tls}
                onChange={(e) => field('smtp_use_tls', e.target.checked)}
              />{' '}
              Use TLS
            </label>
            <label className="od-admin-field">
              Default sender email
              <input
                className="od-admin-input"
                type="email"
                value={form.smtp_default_sender}
                onChange={(e) => field('smtp_default_sender', e.target.value)}
              />
            </label>
          </fieldset>
          <p className="od-admin-hint">
            Save changes before testing. The test checks the saved connection and authentication
            without sending email.
          </p>
          {lastTested ? <p className="od-admin-hint">Last tested: {lastTested}</p> : null}
          <div className="od-admin-actions">
            <Button type="submit" variant="primary" disabled={disabled}>
              {busy ? 'Working…' : 'Save settings'}
            </Button>
            <Button disabled={disabled} onClick={testConnection}>
              Test connection
            </Button>
          </div>
          <details className="od-admin-panel">
            <summary>SMTP setup help</summary>
            <h3>Option 1: Use your internet service provider’s SMTP server</h3>
            <p>
              This is often the simplest choice. Check your ISP’s support site or contact its
              support team for the server hostname and connection settings. A hostname may look like{' '}
              <code>smtp.yourisp.com</code>.
            </p>
            <h3>Option 2: Use Gmail SMTP</h3>
            <p>
              Gmail commonly uses <code>smtp.gmail.com</code> on port <code>587</code> with TLS. If
              your account requires an app password, follow Google’s current account-security
              instructions.
            </p>
            <h3>Option 3: Use a professional SMTP service</h3>
            <p>Examples include SendGrid, Amazon Simple Email Service, Mailgun, and SMTP2GO.</p>
            <p>
              Use TLS when your provider supports it and confirm the port and sender address with
              that provider. A successful test checks connection and authentication; it does not
              confirm email delivery.
            </p>
          </details>
        </form>
      )}
    </Page>
  )
}
