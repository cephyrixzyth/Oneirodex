import { useEffect, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'

interface RetroAchievementsSettings {
  username: string | null
  has_key: boolean
  username_source: 'environment' | 'admin' | null
  key_source: 'environment' | 'admin' | null
}

const ENDPOINT = '/api/admin/integrations/retroachievements'

export function RetroAchievementsSettingsPanel() {
  const [settings, setSettings] = useState<RetroAchievementsSettings | null>(null)
  const [username, setUsername] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = (await getJson(ENDPOINT)) as RetroAchievementsSettings
      setSettings(data)
      setUsername(data.username || '')
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function save() {
    setBusy(true)
    setMessage('Saving…')
    try {
      const data = (await putJson(ENDPOINT, {
        username,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        ...(clearKey ? { clear_api_key: true } : {}),
      })) as RetroAchievementsSettings
      setSettings(data)
      setUsername(data.username || '')
      setApiKey('')
      setClearKey(false)
      setMessage('Saved. The API key is stored on this Oneirodex server.')
    } catch (err) {
      setMessage(errorText(err) || 'Could not save RetroAchievements settings.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="od-admin-panel"
      id="retro-achievements-settings"
      aria-labelledby="od-ra-settings-heading"
    >
      <h2 id="od-ra-settings-heading" className="od-section-head__title">
        RetroAchievements
      </h2>
      <p className="od-admin-lede">
        Connect the household account whose web API key will look up achievement sets and member
        progress. The key is never shown after saving. Environment values take precedence over these
        settings.
      </p>
      <PageStatus
        loading={loading}
        loadingMessage="Reading RetroAchievements settings…"
        error={error}
        onRetry={load}
        errorMessage="Could not read RetroAchievements settings."
        inline
      >
        <div>
          <label className="od-admin-field" htmlFor="ra-admin-username">
            RetroAchievements username
            <input
              id="ra-admin-username"
              className="od-admin-input"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              maxLength={64}
            />
            {settings?.username_source === 'environment' ? (
              <small className="od-muted">Using the username from the server environment.</small>
            ) : null}
          </label>
          <label className="od-admin-field" htmlFor="ra-admin-api-key">
            Web API key
            <input
              id="ra-admin-api-key"
              className="od-admin-input"
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              maxLength={512}
              placeholder={
                settings?.has_key
                  ? 'Key saved — enter a new key to replace it'
                  : 'Paste web API key'
              }
            />
            <small className="od-muted">
              Get the web API key from retroachievements.org → Settings → Keys. Leave blank to keep
              the saved key.
              {settings?.key_source === 'environment'
                ? ' The server environment key is active.'
                : ''}
            </small>
          </label>
        </div>
        {settings?.has_key && settings.key_source !== 'environment' ? (
          <label className="od-admin-field od-admin-field--check" htmlFor="ra-admin-clear-key">
            <input
              id="ra-admin-clear-key"
              type="checkbox"
              checked={clearKey}
              onChange={(event) => setClearKey(event.target.checked)}
            />
            Clear the saved API key
          </label>
        ) : null}
        <div className="od-admin-actions-row">
          <Button
            type="button"
            className="od-btn"
            disabled={
              busy ||
              (settings?.key_source === 'environment' && settings.username_source === 'environment')
            }
            onClick={save}
          >
            {busy ? 'Saving…' : 'Save RetroAchievements'}
          </Button>
          {message ? <PageStatus emptyMessage={message} inline /> : null}
        </div>
        <p className="od-muted">
          Read-only integration: matching only shows community sets and progress; playing in the
          browser does not unlock achievements.
        </p>
      </PageStatus>
    </section>
  )
}
