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
      setError('Client ID and Secret must be at least 20 characters long')
      return
    }
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
      setSecret('')
      setShowSecret(false)
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
      title="IGDB metadata"
      lede="Configure the credentials used to match games and retrieve metadata."
    >
      <PageStatus loading={loading} loadingMessage="Loading IGDB settings…" error={error || null} />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>Retry loading settings</Button>
      ) : null}
      {!loading ? (
        <form className="od-admin-panel" onSubmit={save}>
          <fieldset className="od-admin-fieldset" disabled={disabled}>
            <legend>API credentials</legend>
            <label className="od-admin-field">
              Client ID
              <input
                className="od-admin-input"
                autoComplete="off"
                maxLength={255}
                id="igdb_client_id"
                value={clientId}
                onChange={(e) => {
                  setClientId(e.target.value)
                  setMessage('')
                }}
              />
            </label>
            <label className="od-admin-field" htmlFor="igdb_client_secret">
              Client secret
            </label>
            <input
              id="igdb_client_secret"
              className="od-admin-input"
              type={showSecret ? 'text' : 'password'}
              autoComplete="new-password"
              maxLength={255}
              data-saved={secretPresent ? '1' : '0'}
              aria-describedby="igdb-secret-help"
              value={secret}
              onChange={(e) => {
                setSecret(e.target.value)
                setMessage('')
              }}
            />
            <Button
              aria-controls="igdb_client_secret"
              aria-pressed={showSecret}
              onClick={() => setShowSecret((value) => !value)}
            >
              {showSecret ? 'Hide entered secret' : 'Show entered secret'}
            </Button>
            <p id="igdb-secret-help" className="od-admin-hint">
              {secretPresent ? 'A secret is saved. Leave blank to keep it.' : 'No secret is saved.'}{' '}
              Only a newly entered secret can be shown.
            </p>
          </fieldset>
          {lastTested ? <p className="od-admin-hint">Last connection test: {lastTested}</p> : null}
          <p className="od-admin-hint">
            Testing contacts IGDB using the saved credentials; unsaved edits are not included.
          </p>
          <div className="od-admin-actions-row">
            <Button variant="primary" type="submit" disabled={disabled}>
              {busy ? 'Working…' : 'Save settings'}
            </Button>
            <Button disabled={disabled} onClick={testConnection}>
              Test connection
            </Button>
          </div>
          {message ? (
            <PageStatus announcement="status" className="od-admin-hint">
              {message}
            </PageStatus>
          ) : null}
          <details className="od-admin-panel">
            <summary>Credential setup instructions</summary>
            <p>
              Use the{' '}
              <a href="https://dev.twitch.tv/console" target="_blank" rel="noopener noreferrer">
                Twitch Developer Console
              </a>{' '}
              to manage your application credentials. Follow the provider’s current instructions,
              then enter the client ID and secret here.
            </p>
          </details>
        </form>
      ) : null}
    </Page>
  )
}
