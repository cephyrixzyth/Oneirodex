import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { getJson, putJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'

const API = '/api/admin/igdb/settings'
export function IgdbSettingsPage() {
  const [clientId, setClientId] = useState('')
  const [secret, setSecret] = useState('')
  const [savedId, setSavedId] = useState('')
  const [secretPresent, setSecretPresent] = useState(false)
  const [lastTested, setLastTested] = useState<string | null>(null)
  const [showSecret, setShowSecret] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const dirty = clientId !== savedId || Boolean(secret)
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
    setSavedId(data.igdb_client_id)
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
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await putJson(API, { igdb_client_id: clientId, igdb_client_secret: secret })
      accept(data.settings)
      setMessage('IGDB settings saved.')
      showToast('IGDB settings saved.', 'success')
    } catch (err) {
      const text = errorText(err) || 'Could not save IGDB settings.'
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy(false)
    }
  }
  async function testConnection() {
    if (loading || loadFailed || busy || dirty || !savedId || !secretPresent) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await postJson('/api/admin/igdb/test')
      accept(data.settings)
      setMessage('IGDB connection successful.')
      showToast('IGDB connection successful.', 'success')
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
                value={clientId}
                onChange={(e) => {
                  setClientId(e.target.value)
                  setMessage('')
                }}
              />
            </label>
            <label className="od-admin-field" htmlFor="igdb-new-secret">
              Client secret
            </label>
            <input
              id="igdb-new-secret"
              className="od-admin-input"
              type={showSecret ? 'text' : 'password'}
              autoComplete="new-password"
              maxLength={255}
              aria-describedby="igdb-secret-help"
              value={secret}
              onChange={(e) => {
                setSecret(e.target.value)
                setMessage('')
              }}
            />
            <Button
              aria-controls="igdb-new-secret"
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
            Save changes before testing. Testing contacts IGDB using the saved credentials.
          </p>
          <div className="od-admin-actions-row">
            <Button variant="primary" type="submit" disabled={disabled}>
              {busy ? 'Working…' : 'Save settings'}
            </Button>
            <Button
              disabled={disabled || dirty || !savedId || !secretPresent}
              onClick={testConnection}
            >
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
