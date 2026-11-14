import { useEffect, useRef, useState } from 'react'
import { Button, confirmAction, type AccountLoginSession } from '@oneirodex/ui'
import { createToken, listTokens, revokeToken } from '../api/tokens'
import {
  listAccountLoginSessions,
  revokeAccountLoginSession,
  revokeAllAccountLoginSessions,
} from '../api/sessions'
import { PageStatus } from '../components/PageStatus'
import { copyText } from '../utils/copyText'
import { showToast } from '../utils/toast'
import '../styles/panelGrid.css'
import './TokensPage.css'

const PRESET_FALLBACK: Record<string, any> = {
  companion: {
    label: 'Desktop companion',
    scopes: ['read:library', 'write:download', 'write:presence'],
    hint: 'Library browse, download and device heartbeat for the full Tauri companion.',
  },
  thin: {
    label: 'Thin client',
    scopes: ['read:library', 'read:social', 'write:presence'],
    hint: 'Library + social/presence — no download scope.',
  },
}

function formatWhen(iso: string | null | undefined) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return String(iso)
  }
}

export function TokensPage() {
  const [tokens, setTokens] = useState<any[]>([])
  const [presets, setPresets] = useState(PRESET_FALLBACK)
  const [error, setError] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [preset, setPreset] = useState('companion')
  const [createdSecret, setCreatedSecret] = useState<any>(null)
  const [copyState, setCopyState] = useState('idle')
  const [retryCount, setRetryCount] = useState(0)
  const [sessions, setSessions] = useState<AccountLoginSession[]>([])
  const [sessionsError, setSessionsError] = useState<any>(null)
  const [sessionsBusy, setSessionsBusy] = useState(false)
  const [sessionsRetry, setSessionsRetry] = useState(0)
  const secretInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setError(null)

    listTokens({ signal: controller.signal })
      .then((data) => {
        if (!active) return
        setTokens(Array.isArray(data.tokens) ? data.tokens : [])
        if (data.scope_presets && typeof data.scope_presets === 'object') {
          setPresets({ ...PRESET_FALLBACK, ...data.scope_presets })
        }
      })
      .catch((err: any) => {
        if (active && err.name !== 'AbortError') {
          setError(err)
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [retryCount])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setSessionsError(null)
    listAccountLoginSessions({ signal: controller.signal })
      .then((data) => {
        if (active) setSessions(Array.isArray(data.sessions) ? data.sessions : [])
      })
      .catch((err: any) => {
        if (active && err.name !== 'AbortError') setSessionsError(err)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [sessionsRetry])

  async function refresh() {
    const data = await listTokens()
    setTokens(Array.isArray(data.tokens) ? data.tokens : [])
    if (data.scope_presets && typeof data.scope_presets === 'object') {
      setPresets({ ...PRESET_FALLBACK, ...data.scope_presets })
    }
  }

  async function onCreate(event: any) {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setError(null)
    setCopyState('idle')
    try {
      const result = await createToken({
        name: trimmed,
        preset: preset as 'companion' | 'thin',
      })
      const secret = typeof result.secret === 'string' ? result.secret.trim() : ''
      if (!secret) {
        throw new Error('Create token succeeded but no one-time secret was returned.')
      }
      setCreatedSecret({
        secret,
        warning: result.warning || 'Store this secret now; it will not be shown again.',
        name: result.token?.name || trimmed,
        prefix: result.token?.token_prefix || '',
      })
      setName('')
      await refresh()
    } catch (err: any) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function onRevoke(tokenId: number, tokenName: string) {
    if (busy) return
    const ok = await confirmAction({
      title: `Revoke token “${tokenName}”?`,
      body: 'Clients using it will stop working.',
      confirmLabel: 'Revoke token',
      cancelLabel: 'Keep it',
    })
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      await revokeToken(tokenId)
      await refresh()
    } catch (err: any) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function onRevokeSession(session: AccountLoginSession) {
    if (sessionsBusy) return
    const ok = await confirmAction({
      title: session.current ? 'Sign out this browser?' : 'Revoke this browser session?',
      body: 'That session will need to sign in again.',
      confirmLabel: session.current ? 'Sign out' : 'Revoke session',
      cancelLabel: 'Keep session',
    })
    if (!ok) return
    setSessionsBusy(true)
    setSessionsError(null)
    try {
      await revokeAccountLoginSession(session.id)
      if (session.current) {
        window.location.assign('/login')
      } else {
        setSessionsRetry((count) => count + 1)
      }
    } catch (err: any) {
      setSessionsError(err)
    } finally {
      setSessionsBusy(false)
    }
  }

  async function onRevokeAllSessions() {
    if (sessionsBusy || sessions.length === 0) return
    const ok = await confirmAction({
      title: 'Sign out on all devices?',
      body: 'All browser sessions, including this one, will need to sign in again.',
      confirmLabel: 'Sign out everywhere',
      cancelLabel: 'Keep sessions',
    })
    if (!ok) return
    setSessionsBusy(true)
    setSessionsError(null)
    try {
      await revokeAllAccountLoginSessions()
      window.location.assign('/login')
    } catch (err: any) {
      setSessionsError(err)
      setSessionsBusy(false)
    }
  }

  function selectSecretForManualCopy() {
    const input = secretInputRef.current
    if (!input) return
    input.focus()
    input.select()
    input.setSelectionRange(0, input.value.length)
  }

  async function copySecret() {
    if (!createdSecret?.secret) return
    // Copy the in-memory string only — never DOM textContent (avoids whitespace /
    // sibling labels / prefix ellipsis leaking into the clipboard).
    const ok = await copyText(createdSecret.secret)
    if (ok) {
      setCopyState('copied')
      showToast('Token secret copied', 'success')
      return
    }
    setCopyState('failed')
    selectSecretForManualCopy()
    showToast('Clipboard unavailable — select the secret and copy manually', 'warn')
  }

  const activeTokens = tokens.filter((row) => !row.revoked)
  const presetMeta = presets[preset] || PRESET_FALLBACK[preset] || PRESET_FALLBACK.companion

  return (
    <div className="od-more-page od-tokens od-panels">
      <div className="od-page-header od-panels__full">
        <h1>API tokens</h1>
      </div>
      <p className="od-more-page__lede">
        Create personal access tokens for the desktop companion. The full secret is shown once —
        paste it into the companion Connect screen; it is stored in the OS keyring, not in this UI.
        Format is <code>gt_&lt;prefix&gt;_&lt;secret&gt;</code>. Hyphens and underscores inside the
        secret are normal (URL-safe) — paste the <strong>entire</strong> string; do not stop at the
        last <code>-</code>. Copy prefers HTTPS; on plain HTTP LAN, use Copy or select the field and
        Ctrl+C / ⌘C.
      </p>

      {error ? (
        <PageStatus
          error={error}
          errorMessage={error.message || 'Unable to load tokens.'}
          onRetry={() => setRetryCount((n) => n + 1)}
          retryLabel="Retry"
        />
      ) : null}

      {createdSecret ? (
        <section className="od-tokens__secret" aria-labelledby="od-tokens-secret-heading">
          <h2 id="od-tokens-secret-heading">New token secret</h2>
          <p className="od-tokens__warning" role="status">
            {createdSecret.warning}
          </p>
          <p className="od-tokens__secret-meta">
            {createdSecret.name}
            {createdSecret.prefix ? ` · prefix ${createdSecret.prefix}` : null}
          </p>
          <label className="od-tokens__secret-label" htmlFor="od-tokens-one-time-secret">
            One-time secret
          </label>
          <input
            ref={secretInputRef}
            id="od-tokens-one-time-secret"
            type="text"
            readOnly
            spellCheck={false}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            className="od-tokens__secret-value"
            value={createdSecret.secret}
            onFocus={(event) => {
              event.target.select()
              event.target.setSelectionRange(0, event.target.value.length)
            }}
          />
          <p className="od-tokens__secret-hint">
            Includes <code>-</code> / <code>_</code> when present — that is expected, not
            truncation.
          </p>
          <div className="od-tokens__secret-actions">
            <Button type="button" variant="primary" onClick={() => void copySecret()}>
              {copyState === 'copied' ? 'Copied' : 'Copy secret'}
            </Button>
            <Button
              type="button"
              onClick={() => {
                setCreatedSecret(null)
                setCopyState('idle')
              }}
            >
              Done
            </Button>
          </div>
          {copyState === 'copied' ? (
            <p role="status" className="od-tokens__copy-status">
              Secret copied. Paste the full token into the companion Connect screen.
            </p>
          ) : null}
          {copyState === 'failed' ? (
            <p role="alert" className="od-tokens__copy-status">
              Clipboard unavailable (common on plain HTTP). The secret field is selected — press
              Ctrl+C / ⌘C and paste the full <code>gt_…</code> string without trimming at{' '}
              <code>-</code>.
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="od-tokens__create" aria-labelledby="od-tokens-create-heading">
        <h2 id="od-tokens-create-heading">Create token</h2>
        <form className="od-tokens__form" onSubmit={(event) => void onCreate(event)}>
          <label className="od-tokens__field">
            <span>Name</span>
            <input
              type="text"
              name="token-name"
              maxLength={100}
              autoComplete="off"
              placeholder="My PC"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
              required
            />
          </label>
          <fieldset className="od-tokens__presets" disabled={busy}>
            <legend>Preset</legend>
            {Object.entries(presets).map(([key, meta]) => (
              <label key={key} className="od-tokens__preset">
                <input
                  type="radio"
                  name="token-preset"
                  value={key}
                  checked={preset === key}
                  onChange={() => setPreset(key)}
                />
                <span>
                  <strong>{meta.label || key}</strong>
                  <span className="od-tokens__preset-scopes">
                    {(meta.scopes || []).join(', ') || '—'}
                  </span>
                  {PRESET_FALLBACK[key]?.hint ? (
                    <span className="od-tokens__preset-hint">{PRESET_FALLBACK[key].hint}</span>
                  ) : null}
                </span>
              </label>
            ))}
          </fieldset>
          <p className="od-tokens__preset-summary">
            Selected scopes: {(presetMeta.scopes || []).join(', ') || '—'}
          </p>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            {busy ? 'Working…' : 'Create token'}
          </Button>
        </form>
      </section>

      <section className="od-tokens__list-wrap" aria-labelledby="od-tokens-list-heading">
        <h2 id="od-tokens-list-heading">Your tokens</h2>
        {activeTokens.length === 0 ? (
          <p className="od-more-page__lede">No active tokens yet.</p>
        ) : (
          <ul className="od-tokens__list">
            {activeTokens.map((row) => (
              <li key={row.id} className="od-tokens__row">
                <div className="od-tokens__row-main">
                  <strong>{row.name}</strong>
                  <span className="od-tokens__prefix">{row.token_prefix}</span>
                  <span className="od-tokens__scopes">{(row.scopes || []).join(', ')}</span>
                  <span className="od-tokens__meta">
                    Created {formatWhen(row.created_at)}
                    {row.last_used_at
                      ? ` · Last used ${formatWhen(row.last_used_at)}`
                      : ' · Never used'}
                  </span>
                </div>
                <Button
                  type="button"
                  disabled={busy}
                  onClick={() => void onRevoke(row.id, row.name)}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="od-tokens__list-wrap" aria-labelledby="od-sessions-heading">
        <h2 id="od-sessions-heading">Browser sessions</h2>
        <p className="od-more-page__lede">
          Sessions expire after 7 days without activity and no later than 30 days after sign-in.
          Signing out here revokes the server session.
        </p>
        {sessionsError ? (
          <PageStatus
            error={sessionsError}
            errorMessage={sessionsError.message || 'Unable to load browser sessions.'}
            onRetry={() => setSessionsRetry((count) => count + 1)}
            retryLabel="Retry"
          />
        ) : sessions.length === 0 ? (
          <p className="od-more-page__lede">No active browser sessions.</p>
        ) : (
          <>
            <ul className="od-tokens__list">
              {sessions.map((row) => (
                <li key={row.id} className="od-tokens__row">
                  <div className="od-tokens__row-main">
                    <strong>{row.current ? 'This browser' : 'Browser session'}</strong>
                    <span className="od-tokens__meta">Signed in {formatWhen(row.created_at)}</span>
                    <span className="od-tokens__meta">
                      Last active {formatWhen(row.last_seen_at)}
                    </span>
                    <span className="od-tokens__meta">Expires {formatWhen(row.expires_at)}</span>
                  </div>
                  <Button
                    type="button"
                    disabled={sessionsBusy}
                    onClick={() => void onRevokeSession(row)}
                  >
                    {row.current ? 'Sign out' : 'Revoke'}
                  </Button>
                </li>
              ))}
            </ul>
            <Button
              type="button"
              variant="secondary"
              disabled={sessionsBusy}
              onClick={() => void onRevokeAllSessions()}
            >
              Sign out on all devices
            </Button>
          </>
        )}
      </section>
    </div>
  )
}
