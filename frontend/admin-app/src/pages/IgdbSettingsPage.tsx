import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'

const API = '/api/admin/igdb/settings'
export function IgdbSettingsPage() {
  const [clientId, setClientId] = useState('')
  const [secret, setSecret] = useState('')
  const [secretPresent, setSecretPresent] = useState(false)
  const [lastTested, setLastTested] = useState<string | null>(null)
  const [showSecret, setShowSecret] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState('')
  const [credentialsInvalid, setCredentialsInvalid] = useState(false)
  const [message, setMessage] = useState('')
  function accept(data: {
    igdb_client_id?: unknown
    secret_present?: unknown
    last_tested?: string | null
  }) {
    if (
      !data ||
      typeof data.igdb_client_id !== 'string' ||
      typeof data.secret_present !== 'boolean'
    )
      throw new Error('IGDB settings returned an invalid response.')
    setClientId(data.igdb_client_id)
    setSecretPresent(data.secret_present)
    setLastTested(data.last_tested || null)
    setSecret('')
    setShowSecret(false)
  }
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson(API)
      .then((data) => {
        if (!cancelled) accept(data.settings)
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
  }, [reload])
  async function save(event: FormEvent) {
    event.preventDefault()
    if (loading || loadFailed || busy) return
    const keepSavedSecret = secret === '' && secretPresent
    if (clientId.length < 20 || (!keepSavedSecret && secret.length < 20)) {
      setCredentialsInvalid(true)
      setError('Client ID and Secret must be at least 20 characters long')
      return
    }
    setCredentialsInvalid(false)
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await postJson('/admin/igdb_settings', {
        igdb_client_id: clientId,
        igdb_client_secret: secret,
      })
      if (data.status !== 'success')
        throw new Error(data.message || 'Could not save IGDB settings.')
      setSecretPresent(secretPresent || Boolean(secret))
      setMessage('IGDB settings saved successfully')
      showToast('IGDB settings saved successfully', 'success')
    } catch (err) {
      const text = errorText(err) || 'Could not save IGDB settings.'
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy(false)
    }
  }
  async function testConnection() {
    if (loading || loadFailed || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await postJson('/admin/test_igdb')
      if (data.status !== 'success') throw new Error(data.message || 'IGDB connection failed.')
      // Refresh the timestamp and secret-presence projection after the legacy
      // test endpoint succeeds; a read failure must not turn a successful
      // provider test into a reported failure.
      void getJson(API)
        .then((settings) => accept(settings.settings))
        .catch(() => {})
      setMessage('IGDB API test successful')
      showToast('IGDB API test successful', 'success')
    } catch (err) {
      const text = errorText(err) || 'IGDB connection failed.'
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy(false)
    }
  }
  const disabled = loading || loadFailed || busy
  return (
    <Page
      title={
        <>
          <svg className="od-igdb-title-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <rect x="2" y="6" width="20" height="12" rx="3" />
            <path d="M6 12h4M8 10v4M15 11h.01M18 13h.01" />
          </svg>
          IGDB API Settings
        </>
      }
      documentTitle="IGDB metadata"
      className="od-igdb-settings-page"
      lede="Configure the credentials used to match games and retrieve metadata."
    >
      <PageStatus loading={loading} loadingMessage="Loading IGDB settings…" error={error || null} />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>Retry loading settings</Button>
      ) : null}
      <details className="od-admin-panel od-igdb-instructions">
        <summary>
          <svg className="od-igdb-instructions__chevron" viewBox="0 0 24 24" aria-hidden="true">
            <path d="m6 9 6 6 6-6" />
          </svg>
          Show Instructions
        </summary>
        <div className="od-igdb-instructions__body">
          <h2>How to Get Your IGDB API Credentials</h2>
          <ol>
            <li>
              Go to the{' '}
              <a href="https://dev.twitch.tv/console" target="_blank" rel="noopener noreferrer">
                Twitch Developer Console
              </a>
            </li>
            <li>Log in with your Twitch account (or create one if needed)</li>
            <li>Click on "Register Your Application"</li>
            <li>
              Fill in the application details:
              <ul>
                <li>Name: Your choice (e.g., "MyOneirodex")</li>
                <li>OAuth Redirect URL: http://localhost (if testing locally)</li>
                <li>Category: Select "Website Integration"</li>
              </ul>
            </li>
            <li>After registering, you'll receive your Client ID</li>
            <li>Click "New Secret" to generate your Client Secret</li>
          </ol>
          <p className="od-igdb-instructions__note">
            <strong>Note:</strong> IGDB is owned by Twitch, which is why credentials are obtained
            through the Twitch Developer Console. The free tier includes 4 requests per second and
            500k requests per month.
          </p>
        </div>
      </details>
      {!loading ? (
        <form className="od-igdb-form" noValidate onSubmit={save}>
          <fieldset className="od-igdb-form__fieldset" disabled={disabled}>
            <legend className="visually-hidden">API credentials</legend>
            <div className="od-igdb-form__group">
              <label className="od-admin-field" htmlFor="igdb_client_id">
                Client ID <span aria-hidden="true">*</span>
              </label>
              <input
                id="igdb_client_id"
                className="od-admin-input"
                autoComplete="off"
                maxLength={50}
                minLength={20}
                required
                aria-invalid={credentialsInvalid && clientId.length < 20}
                value={clientId}
                onChange={(e) => {
                  setClientId(e.target.value)
                  setCredentialsInvalid(false)
                  setError('')
                  setMessage('')
                }}
              />
            </div>
            <div className="od-igdb-form__group">
              <label className="od-admin-field" htmlFor="igdb_client_secret">
                Client Secret
              </label>
              <div className="od-igdb-secret-field">
                <input
                  id="igdb_client_secret"
                  className="od-admin-input"
                  type={showSecret ? 'text' : 'password'}
                  autoComplete="new-password"
                  maxLength={50}
                  minLength={20}
                  placeholder={secretPresent ? 'Saved. Leave blank to keep it' : 'No secret is saved'}
                  aria-invalid={credentialsInvalid && secret.length > 0 && secret.length < 20}
                  data-saved={secretPresent ? '1' : '0'}
                  aria-describedby="igdb-secret-help"
                  value={secret}
                  onChange={(e) => {
                    setSecret(e.target.value)
                    setCredentialsInvalid(false)
                    setError('')
                    setMessage('')
                  }}
                />
                <Button
                  className="od-igdb-secret-toggle"
                  aria-label={showSecret ? 'Hide entered secret' : 'Show entered secret'}
                  aria-controls="igdb_client_secret"
                  aria-pressed={showSecret}
                  title={showSecret ? 'Hide entered secret' : 'Show entered secret'}
                  onClick={() => setShowSecret((value) => !value)}
                >
                  {showSecret ? (
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M3 3l18 18M10.6 10.6a2 2 0 002.8 2.8" />
                      <path d="M9.9 5.2A10.8 10.8 0 0112 5c5.5 0 9.5 7 9.5 7a16 16 0 01-3 3.7M6.2 6.2C3.8 8 2.5 12 2.5 12s4 7 9.5 7a10 10 0 002.4-.3" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M2.5 12s4-7 9.5-7 9.5 7 9.5 7-4 7-9.5 7-9.5-7-9.5-7z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </Button>
                <span id="igdb-secret-help" className="visually-hidden">
                  {secretPresent ? 'A secret is saved. Leave blank to keep it. ' : 'No secret is saved. '}
                  Only a newly entered secret can be shown.
                </span>
              </div>
            </div>
          </fieldset>
          {lastTested ? <p className="od-admin-hint">Last connection test: {lastTested}</p> : null}
          <p id="igdb-test-help" className="visually-hidden">
            Testing contacts IGDB using the saved credentials; unsaved edits are not included.
          </p>
          <div className="od-admin-actions-row od-igdb-actions">
            <Button variant="primary" type="submit" disabled={disabled}>
              {busy ? 'Working…' : 'Save Settings'}
            </Button>
            <Button aria-describedby="igdb-test-help" disabled={disabled} onClick={testConnection}>
              Test Connection
            </Button>
          </div>
          {message ? (
            <PageStatus announcement="status" className="od-admin-hint">
              {message}
            </PageStatus>
          ) : null}
        </form>
      ) : null}
    </Page>
  )
}
