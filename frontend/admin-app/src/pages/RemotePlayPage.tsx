// Toasts on every mutation (GT-B25). These pages reported outcomes with an
// inline message only, which is easy to miss when the control that triggered
// it has scrolled away — and invisible when the save happens from the bottom
// of a long form.
import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { showToast } from '../utils/toast'
import { Page } from '../components/Page'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'

interface RemotePlayForm {
  enabled: boolean
  provider: string
  sunshine_base_url: string
  wolf_base_url: string
  token_hint: string
  pin_hint: string
  app_hint: string
  host_label: string
}

const EMPTY: RemotePlayForm = {
  enabled: false,
  provider: 'sunshine',
  sunshine_base_url: '',
  wolf_base_url: '',
  token_hint: '',
  pin_hint: '',
  app_hint: '',
  host_label: '',
}

export function RemotePlayPage() {
  const [form, setForm] = useState(EMPTY)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loadFailed, setLoadFailed] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    setLoadFailed(false)
    getJson('/api/admin/remote-play/config')
      .then((data) => {
        if (cancelled) return
        setForm({
          enabled: Boolean(data.enabled || data.db_enabled),
          provider: data.provider || 'sunshine',
          sunshine_base_url: data.sunshine_base_url || '',
          wolf_base_url: data.wolf_base_url || '',
          token_hint: data.token_hint || '',
          pin_hint: data.pin_hint || '',
          app_hint: data.app_hint || '',
          host_label: data.host_label || '',
        })
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err) || 'Could not load remote play settings.')
          setLoadFailed(true)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  function updateField<K extends keyof RemotePlayForm>(key: K, value: RemotePlayForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || loading || loadFailed) return
    setBusy(true)
    setMessage('')
    setError('')
    try {
      await putJson('/api/admin/remote-play/config', { ...form })
      setMessage('Remote play settings saved.')
      showToast('Remote play settings saved.', 'success')
    } catch (err) {
      const text = errorText(err) || 'Remote play save failed.'
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page
      title="Remote play"
      lede={
        <>
          Register a BYO Sunshine or Wolf host. Oneirodex does not bundle Wolf/GOW — members use
          Moonlight clients with the hints you set.
        </>
      }
    >
      <PageStatus error={error || null} />
      {loadFailed ? (
        <Button onClick={() => setReloadKey((key) => key + 1)}>Retry loading settings</Button>
      ) : null}
      {loading ? (
        <PageStatus loading loadingMessage="Loading remote play settings…" />
      ) : (
        <form className="od-admin-panel" onSubmit={save}>
          <label className="od-admin-field">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => updateField('enabled', e.target.checked)}
            />{' '}
            Enable remote play (also set <code>ENABLE_REMOTE_PLAY=true</code> in .env to override)
          </label>
          <label className="od-admin-field">
            Primary provider
            <select
              className="od-admin-input"
              value={form.provider}
              onChange={(e) => updateField('provider', e.target.value)}
            >
              <option value="sunshine">Sunshine (single session)</option>
              <option value="wolf">Wolf (multi-user)</option>
            </select>
          </label>
          <label className="od-admin-field">
            Sunshine base URL
            <input
              className="od-admin-input"
              type="url"
              placeholder="http://192.168.1.50:47989"
              value={form.sunshine_base_url}
              onChange={(e) => updateField('sunshine_base_url', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Wolf base URL
            <input
              className="od-admin-input"
              type="url"
              placeholder="http://192.168.1.50:8080"
              value={form.wolf_base_url}
              onChange={(e) => updateField('wolf_base_url', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Host label (shown to members)
            <input
              className="od-admin-input"
              type="text"
              placeholder="Basement GPU PC"
              value={form.host_label}
              onChange={(e) => updateField('host_label', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            App hint (Moonlight app name)
            <input
              className="od-admin-input"
              type="text"
              placeholder="Steam Big Picture"
              value={form.app_hint}
              onChange={(e) => updateField('app_hint', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            PIN hint
            <input
              className="od-admin-input"
              type="text"
              placeholder="Pair in Sunshine first"
              value={form.pin_hint}
              onChange={(e) => updateField('pin_hint', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Token hint
            <input
              className="od-admin-input"
              type="text"
              placeholder="Ask admin for Wolf token"
              value={form.token_hint}
              onChange={(e) => updateField('token_hint', e.target.value)}
            />
          </label>
          <p className="od-admin-hint">
            LAN URLs require <code>ALLOW_PRIVATE_LAN_URLS=true</code>. Oneirodex only stores
            connection hints — it does not run Sunshine/Wolf in the app container.
          </p>
          <div className="od-admin-actions-row">
            <Button type="submit" disabled={busy || loadFailed}>
              {busy ? 'Saving…' : 'Save settings'}
            </Button>
            <a className="od-btn od-btn--ghost" href="/admin/settings">
              Settings hub
            </a>
          </div>
          {message ? <PageStatus announcement="status">{message}</PageStatus> : null}
        </form>
      )}
    </Page>
  )
}
