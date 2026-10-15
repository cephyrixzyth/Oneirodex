import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { getJson, postJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'

type LightingDraft = {
  enabled: boolean
  provider: 'off' | 'hyperion' | 'homeassistant'
  hyperion_url: string
  hyperion_token: string
  hyperion_priority: number
  ambient_accent_color: string
  ha_url: string
  ha_token: string
  ha_light_entities: string
  ha_play_scene: string
  ha_stop_scene: string
}
type LightingConfig = LightingDraft & {
  env_enabled: boolean
  db_enabled: boolean
  enabled: boolean
  hyperion_token_configured: boolean
  ha_token_configured: boolean
}
type LightingStatus = {
  enabled: boolean
  provider: string
  reachable: boolean
  last_error?: string | null
  note?: string
}

const EMPTY: LightingDraft = {
  enabled: false,
  provider: 'off',
  hyperion_url: '',
  hyperion_token: '',
  hyperion_priority: 50,
  ambient_accent_color: '#ff8020',
  ha_url: '',
  ha_token: '',
  ha_light_entities: '',
  ha_play_scene: '',
  ha_stop_scene: '',
}
function toHex(value: unknown): string {
  const raw = String(value || '').trim()
  if (/^#[0-9a-f]{6}$/i.test(raw)) return raw
  const parts = raw
    .replace(/^#/, '')
    .split(/[\s,]+/)
    .map(Number)
  if (parts.length >= 3 && parts.slice(0, 3).every((part) => Number.isFinite(part))) {
    return `#${parts
      .slice(0, 3)
      .map((part) => Math.max(0, Math.min(255, part)).toString(16).padStart(2, '0'))
      .join('')}`
  }
  return EMPTY.ambient_accent_color
}
function draftFrom(config: LightingConfig): LightingDraft {
  if (!config || !['off', 'hyperion', 'homeassistant'].includes(config.provider)) {
    throw new Error('Ambient-lighting settings returned an invalid response.')
  }
  return {
    enabled: Boolean(config.db_enabled),
    provider: config.provider,
    hyperion_url: String(config.hyperion_url || ''),
    hyperion_token: '',
    hyperion_priority: Number.isInteger(config.hyperion_priority) ? config.hyperion_priority : 50,
    ambient_accent_color: toHex(config.ambient_accent_color),
    ha_url: String(config.ha_url || ''),
    ha_token: '',
    ha_light_entities: Array.isArray(config.ha_light_entities)
      ? config.ha_light_entities.join(', ')
      : '',
    ha_play_scene: String(config.ha_play_scene || ''),
    ha_stop_scene: String(config.ha_stop_scene || ''),
  }
}
function payloadFrom(draft: LightingDraft) {
  return {
    ...draft,
    ha_light_entities: draft.ha_light_entities
      .split(/[\s,]+/)
      .map((entry) => entry.trim())
      .filter(Boolean),
  }
}

export function AmbientLightingPanel() {
  const [draft, setDraft] = useState<LightingDraft | null>(null)
  const [saved, setSaved] = useState<LightingDraft | null>(null)
  const [config, setConfig] = useState<LightingConfig | null>(null)
  const [status, setStatus] = useState<LightingStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const pending = useRef(false)
  const dirty = useMemo(
    () => Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved)),
    [draft, saved],
  )
  const canProbe = Boolean(
    draft &&
    config?.enabled &&
    !dirty &&
    (draft.provider === 'hyperion'
      ? draft.hyperion_url.trim()
      : draft.provider === 'homeassistant' &&
        draft.ha_url.trim() &&
        (config.ha_token_configured || draft.ha_token.trim())),
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError('')
    setError('')
    Promise.all([
      getJson('/api/admin/ambient-lighting/config'),
      getJson('/api/admin/ambient-lighting/status'),
    ])
      .then(([nextConfig, nextStatus]) => {
        if (cancelled) return
        const nextDraft = draftFrom(nextConfig as LightingConfig)
        setConfig(nextConfig as LightingConfig)
        setDraft(nextDraft)
        setSaved(nextDraft)
        setStatus(nextStatus as LightingStatus)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(errorText(err) || 'Could not load ambient-lighting settings.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reload])

  async function run(work: () => Promise<void>) {
    if (loading || loadError || pending.current) return
    pending.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await work()
    } catch (err) {
      setError(errorText(err) || 'Could not complete the action.')
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  function save(event: FormEvent) {
    event.preventDefault()
    if (!draft) return
    void run(async () => {
      const result = await putJson('/api/admin/ambient-lighting/config', payloadFrom(draft))
      const accepted = draftFrom(result as LightingConfig)
      setDraft(accepted)
      setSaved(accepted)
      setConfig(result as LightingConfig)
      setMessage('Ambient-lighting settings saved. Credentials remain stored securely.')
    })
  }

  async function testConnection() {
    if (!draft || dirty || !config?.enabled || draft.provider === 'off') return
    if (
      !(await confirmAction({
        title: 'Test the lighting connection?',
        body: 'This contacts the configured connector and may briefly turn on lights or a Home Assistant scene. Save current settings first; this test does not restore a previous scene.',
        confirmLabel: 'Test connection',
        tone: 'neutral',
      }))
    )
      return
    await run(async () => {
      const result = await postJson('/api/admin/ambient-lighting/test')
      setStatus(result as LightingStatus)
      if (result?.probe_ok) setMessage('Lighting connection test succeeded.')
      else setError(result?.last_error || 'The lighting connection did not respond successfully.')
    })
  }

  const disabled = loading || Boolean(loadError) || busy || !draft
  return (
    <section className="od-admin-panel" aria-labelledby="ambient-lighting-title">
      <h2 id="ambient-lighting-title">Ambient lighting</h2>
      <p className="od-admin-hint">
        Optional Hyperion.ng or Home Assistant lighting while a game is playing. Saving settings
        never contacts the connector. Child accounts do not trigger lighting.
      </p>
      <PageStatus
        loading={loading}
        loadingMessage="Loading ambient-lighting settings…"
        error={loadError || null}
      />
      {loadError ? (
        <Button
          type="button"
          className="od-btn--secondary"
          onClick={() => setReload((value) => value + 1)}
        >
          Retry loading settings
        </Button>
      ) : null}
      {error ? (
        <PageStatus announcement="alert" className="od-error">
          {error}
        </PageStatus>
      ) : null}
      {message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      {draft ? (
        <form onSubmit={save}>
          <fieldset className="od-admin-fieldset" disabled={disabled}>
            <legend>Connector settings</legend>
            <label className="od-admin-field">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
              />{' '}
              Enable in database settings
            </label>
            <p className="od-admin-hint">
              Effective: {config?.enabled ? 'enabled' : 'disabled'} · process override:{' '}
              {config?.env_enabled ? 'on' : 'off'}.
            </p>
            <label className="od-admin-field">
              Provider
              <select
                className="od-admin-input"
                value={draft.provider}
                onChange={(event) =>
                  setDraft({ ...draft, provider: event.target.value as LightingDraft['provider'] })
                }
              >
                <option value="off">Off</option>
                <option value="hyperion">Hyperion.ng</option>
                <option value="homeassistant">Home Assistant</option>
              </select>
            </label>
            <label className="od-admin-field">
              Accent color
              <input
                className="od-admin-input"
                type="color"
                value={draft.ambient_accent_color}
                onChange={(event) =>
                  setDraft({ ...draft, ambient_accent_color: event.target.value })
                }
              />
            </label>
            {draft.provider === 'hyperion' ? (
              <>
                <label className="od-admin-field">
                  Hyperion URL
                  <input
                    className="od-admin-input"
                    type="url"
                    required
                    maxLength={2048}
                    value={draft.hyperion_url}
                    onChange={(event) => setDraft({ ...draft, hyperion_url: event.target.value })}
                  />
                </label>
                <label className="od-admin-field">
                  Hyperion token{' '}
                  <span className="od-admin-hint">
                    {config?.hyperion_token_configured
                      ? 'A token is saved. Leave blank to retain it.'
                      : 'Optional; leave blank when unused.'}
                  </span>
                  <input
                    className="od-admin-input"
                    aria-label="Hyperion token"
                    type="password"
                    autoComplete="new-password"
                    value={draft.hyperion_token}
                    onChange={(event) => setDraft({ ...draft, hyperion_token: event.target.value })}
                  />
                </label>
                <label className="od-admin-field">
                  Priority
                  <input
                    className="od-admin-input"
                    type="number"
                    min="0"
                    max="255"
                    step="1"
                    value={draft.hyperion_priority}
                    onChange={(event) =>
                      setDraft({ ...draft, hyperion_priority: Number(event.target.value) })
                    }
                  />
                </label>
              </>
            ) : null}
            {draft.provider === 'homeassistant' ? (
              <>
                <label className="od-admin-field">
                  Home Assistant URL
                  <input
                    className="od-admin-input"
                    type="url"
                    required
                    maxLength={2048}
                    value={draft.ha_url}
                    onChange={(event) => setDraft({ ...draft, ha_url: event.target.value })}
                  />
                </label>
                <label className="od-admin-field">
                  Home Assistant token{' '}
                  <span className="od-admin-hint">
                    {config?.ha_token_configured
                      ? 'A token is saved. Leave blank to retain it.'
                      : 'Required for Home Assistant.'}
                  </span>
                  <input
                    className="od-admin-input"
                    aria-label="Home Assistant token"
                    type="password"
                    autoComplete="new-password"
                    value={draft.ha_token}
                    onChange={(event) => setDraft({ ...draft, ha_token: event.target.value })}
                  />
                </label>
                <label className="od-admin-field">
                  Light entities
                  <input
                    className="od-admin-input"
                    value={draft.ha_light_entities}
                    onChange={(event) =>
                      setDraft({ ...draft, ha_light_entities: event.target.value })
                    }
                    placeholder="light.living_room, light.tv_backlight"
                  />
                </label>
                <label className="od-admin-field">
                  Scene while playing
                  <input
                    className="od-admin-input"
                    value={draft.ha_play_scene}
                    onChange={(event) => setDraft({ ...draft, ha_play_scene: event.target.value })}
                  />
                </label>
                <label className="od-admin-field">
                  Scene when play stops
                  <input
                    className="od-admin-input"
                    value={draft.ha_stop_scene}
                    onChange={(event) => setDraft({ ...draft, ha_stop_scene: event.target.value })}
                  />
                </label>
              </>
            ) : null}
            <p className="od-admin-hint">
              Status: {status?.enabled ? 'enabled' : 'disabled'} ·{' '}
              {status?.reachable
                ? 'connector URL validated'
                : 'connector not reachable or not configured'}
              .
            </p>
            {status?.last_error ? (
              <p className="od-admin-hint">Last connector error: {status.last_error}</p>
            ) : null}
          </fieldset>
          <div className="od-admin-actions-row">
            <Button type="submit" variant="primary" disabled={disabled || !dirty}>
              Save lighting settings
            </Button>
            <Button
              type="button"
              className="od-btn--secondary"
              disabled={disabled || !canProbe}
              onClick={() => void testConnection()}
            >
              Test connection
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  )
}
