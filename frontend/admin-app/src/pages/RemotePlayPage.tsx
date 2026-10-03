// Toasts on every mutation (GT-B25). These pages reported outcomes with an
// inline message only, which is easy to miss when the control that triggered
// it has scrolled away — and invisible when the save happens from the bottom
// of a long form.
import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { showToast } from '../utils/toast'
import { Page } from '../components/Page'

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
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch('/api/admin/remote-play/config', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
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
      .catch(() => {
        if (!cancelled) setMessage('Could not load remote play settings.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function updateField<K extends keyof RemotePlayForm>(key: K, value: RemotePlayForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setMessage('')
    try {
      const response = await fetch('/api/admin/remote-play/config', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: form.enabled,
          provider: form.provider,
          sunshine_base_url: form.sunshine_base_url,
          wolf_base_url: form.wolf_base_url,
          token_hint: form.token_hint,
          pin_hint: form.pin_hint,
          app_hint: form.app_hint,
          host_label: form.host_label,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.error || 'Save failed.')
        showToast(data.error || 'Remote play save failed.', 'error')
        return
      }
      setMessage('Remote play settings saved.')
      showToast('Remote play settings saved.', 'success')
    } catch {
      setMessage('Save failed.')
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
            <select value={form.provider} onChange={(e) => updateField('provider', e.target.value)}>
              <option value="sunshine">Sunshine (single session)</option>
              <option value="wolf">Wolf (multi-user)</option>
            </select>
          </label>
          <label className="od-admin-field">
            Sunshine base URL
            <input
              type="url"
              placeholder="http://192.168.1.50:47989"
              value={form.sunshine_base_url}
              onChange={(e) => updateField('sunshine_base_url', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Wolf base URL
            <input
              type="url"
              placeholder="http://192.168.1.50:8080"
              value={form.wolf_base_url}
              onChange={(e) => updateField('wolf_base_url', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Host label (shown to members)
            <input
              type="text"
              placeholder="Basement GPU PC"
              value={form.host_label}
              onChange={(e) => updateField('host_label', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            App hint (Moonlight app name)
            <input
              type="text"
              placeholder="Steam Big Picture"
              value={form.app_hint}
              onChange={(e) => updateField('app_hint', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            PIN hint
            <input
              type="text"
              placeholder="Pair in Sunshine first"
              value={form.pin_hint}
              onChange={(e) => updateField('pin_hint', e.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Token hint
            <input
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
            <Button type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Save settings'}
            </Button>
            <a className="od-btn od-btn--ghost" href="/admin/settings">
              Settings hub
            </a>
          </div>
          {message ? <p role="status">{message}</p> : null}
        </form>
      )}
    </Page>
  )
}
