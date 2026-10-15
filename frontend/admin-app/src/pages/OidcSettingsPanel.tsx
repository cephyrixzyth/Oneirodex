import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import './OidcSettingsPanel.css'

type OidcSettings = {
  oidc_enabled: boolean
  oidc_display_name: string
  oidc_issuer_url: string
  oidc_client_id: string
  oidc_client_secret: string
  oidc_client_secret_configured: boolean
  oidc_redirect_uri: string
  oidc_scopes: string
  oidc_role_claim: string
  oidc_role_map: string
}
type Readiness = { ready: boolean; message: string; missing: string[] }
type Response = { settings: OidcSettings; readiness: Readiness }
const endpoint = '/api/admin/integrations/oidc'
const emptySettings: OidcSettings = {
  oidc_enabled: false,
  oidc_display_name: 'Sign in with SSO',
  oidc_issuer_url: '',
  oidc_client_id: '',
  oidc_client_secret: '',
  oidc_client_secret_configured: false,
  oidc_redirect_uri: '',
  oidc_scopes: 'openid email profile',
  oidc_role_claim: 'groups',
  oidc_role_map:
    '{\n  "admin": "admin",\n  "oneirodex-admin": "admin",\n  "librarian": "librarian",\n  "oneirodex-librarian": "librarian",\n  "child": "child",\n  "oneirodex-child": "child"\n}',
}

export function OidcSettingsPanel() {
  const [settings, setSettings] = useState<OidcSettings>(emptySettings)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson(endpoint)
      .then((response: Response) => {
        if (cancelled) return
        if (!response?.settings || !response?.readiness)
          throw new Error('OIDC settings response was incomplete.')
        setSettings({
          ...response.settings,
          oidc_client_secret: '',
          oidc_role_map: JSON.stringify(response.settings.oidc_role_map, null, 2),
        })
        setReadiness(response.readiness)
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(errorText(reason))
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

  function update<K extends keyof OidcSettings>(key: K, value: OidcSettings[K]) {
    setSettings((current) => ({ ...current, [key]: value }))
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    if (loading || loadFailed || saving) return
    let roleMap: unknown
    try {
      roleMap = JSON.parse(settings.oidc_role_map)
    } catch {
      setError('Role map must be valid JSON.')
      return
    }
    setError('')
    setMessage('')
    setSaving(true)
    try {
      const { oidc_client_secret_configured: _secretPresence, ...formSettings } = settings
      const result = await putJson(endpoint, { ...formSettings, oidc_role_map: roleMap })
      setSettings({
        ...result.settings,
        oidc_client_secret: '',
        oidc_role_map: JSON.stringify(result.settings.oidc_role_map, null, 2),
      })
      setReadiness(result.readiness)
      setMessage('OIDC settings saved.')
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setSaving(false)
    }
  }

  const disabled = loading || loadFailed || saving
  return (
    <section
      id="oidc"
      className="od-admin-panel od-admin-panel--stacked od-oidc-panel"
      aria-labelledby="oidc-heading"
    >
      <h2 id="oidc-heading">OIDC / SSO</h2>
      <p className="od-admin-lede">
        Optional single sign-on. Saving settings does not contact the identity provider.
      </p>
      {loading ? <PageStatus loading loadingMessage="Loading OIDC settings..." /> : null}
      {error ? (
        <PageStatus announcement="alert" className="od-admin-error">
          {error}
        </PageStatus>
      ) : null}
      {loadFailed ? (
        <Button disabled={loading} onClick={() => setReload((value) => value + 1)}>
          Retry loading OIDC settings
        </Button>
      ) : null}
      {readiness ? (
        <PageStatus announcement="status" className="od-oidc-readiness">
          {readiness.message}
        </PageStatus>
      ) : null}
      {message ? <PageStatus announcement="status">{message}</PageStatus> : null}
      {!loadFailed ? (
        <form onSubmit={save} className="od-oidc-form">
          <fieldset className="od-admin-fieldset" disabled={disabled}>
            <legend>Identity provider</legend>
            <label className="od-admin-field">
              <input
                type="checkbox"
                checked={settings.oidc_enabled}
                onChange={(event) => update('oidc_enabled', event.target.checked)}
              />{' '}
              Enable OIDC
            </label>
            <label className="od-admin-field">
              Sign-in display name
              <input
                className="od-admin-input"
                value={settings.oidc_display_name}
                maxLength={120}
                onChange={(event) => update('oidc_display_name', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Issuer URL
              <input
                className="od-admin-input"
                type="url"
                value={settings.oidc_issuer_url}
                maxLength={512}
                autoComplete="url"
                onChange={(event) => update('oidc_issuer_url', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Client ID
              <input
                className="od-admin-input"
                value={settings.oidc_client_id}
                maxLength={255}
                autoComplete="off"
                onChange={(event) => update('oidc_client_id', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Client secret
              <input
                className="od-admin-input"
                type="password"
                value={settings.oidc_client_secret}
                maxLength={512}
                autoComplete="new-password"
                onChange={(event) => update('oidc_client_secret', event.target.value)}
                placeholder={
                  settings.oidc_client_secret_configured ? 'Saved; leave blank to keep it' : ''
                }
              />
            </label>
            <label className="od-admin-field">
              Redirect URI
              <input
                className="od-admin-input"
                type="url"
                value={settings.oidc_redirect_uri}
                maxLength={512}
                autoComplete="url"
                onChange={(event) => update('oidc_redirect_uri', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Scopes
              <input
                className="od-admin-input"
                value={settings.oidc_scopes}
                maxLength={255}
                onChange={(event) => update('oidc_scopes', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Role claim
              <input
                className="od-admin-input"
                value={settings.oidc_role_claim}
                maxLength={64}
                onChange={(event) => update('oidc_role_claim', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Role map (JSON)
              <textarea
                className="od-admin-input od-oidc-role-map"
                value={settings.oidc_role_map}
                rows={8}
                onChange={(event) => update('oidc_role_map', event.target.value)}
              />
            </label>
            <Button type="submit" disabled={disabled}>
              {saving ? 'Saving...' : 'Save OIDC settings'}
            </Button>
          </fieldset>
        </form>
      ) : null}
    </section>
  )
}
