import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { createToken, extractOneTimeSecret, listTokens, revokeToken } from '../tokensApi.js'
import type { ApiToken } from '../tokensApi.js'
import { copyText } from '../copyText.js'
import { formatWhen, messageOf } from './accountModalShared'
import { Note } from './AccountPanels'

/* TokensPanel moved out of AccountModal (v11 cycle, H-D.2) — unchanged. */

export type ScopePresetId = 'companion' | 'thin'

export function TokensPanel(): ReactNode {
  const [tokens, setTokens] = useState<ApiToken[]>([])
  const [name, setName] = useState('')
  const [preset, setPreset] = useState<ScopePresetId>('companion')
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const nameInputRef = useRef<HTMLInputElement | null>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await listTokens({ signal })
      setTokens(Array.isArray(data.tokens) ? data.tokens : [])
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err, 'Could not load your tokens.'))
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !name.trim()) return
    setBusy(true)
    setError('')
    try {
      const data = await createToken({ name: name.trim(), preset })
      setSecret(extractOneTimeSecret(data))
      setName('')
      await load()
    } catch (err) {
      setError(messageOf(err, 'Could not create that token.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleRevoke(id: number) {
    setError('')
    try {
      await revokeToken(id)
      await load()
    } catch (err) {
      setError(messageOf(err, 'Could not revoke that token.'))
    }
  }

  function dismissSecret() {
    setSecret('')
    nameInputRef.current?.focus()
  }

  return (
    <>
      <Note tone="error">{error}</Note>

      {secret ? (
        <div className="od-acct__note od-acct__note--good" role="status">
          <p style={{ margin: 0 }}>Copy this now — it is not shown again.</p>
          <code className="od-acct__link">{secret}</code>
          <div className="od-acct__actions">
            <button type="button" className="od-cbtn" onClick={() => copyText(secret)}>
              Copy token
            </button>
            <button type="button" className="od-cbtn" onClick={dismissSecret}>
              Done
            </button>
          </div>
        </div>
      ) : null}

      <form onSubmit={handleCreate}>
        <label className="od-acct__field">
          <span className="od-acct__label">Token name</span>
          <input
            ref={nameInputRef}
            className="od-acct__input"
            value={name}
            placeholder="Living room companion"
            onChange={(event) => setName(event.target.value)}
            required
          />
        </label>

        <label className="od-acct__field">
          <span className="od-acct__label">Scope preset</span>
          <select
            className="od-acct__input"
            value={preset}
            onChange={(event) => setPreset(event.target.value as ScopePresetId)}
          >
            <option value="companion">Desktop companion — library + download</option>
            <option value="thin">Thin client — library + social, no download</option>
          </select>
        </label>

        <div className="od-acct__actions">
          <button
            type="submit"
            className="od-cbtn od-cbtn--primary"
            disabled={busy || !name.trim()}
          >
            {busy ? 'Creating…' : 'Create token'}
          </button>
        </div>
      </form>

      <ul className="od-acct__list od-acct__list--follow">
        {tokens.length === 0 ? (
          <p className="od-acct__empty">No tokens yet.</p>
        ) : (
          tokens.map((token) => (
            <li key={token.id} className="od-acct__row">
              <div className="od-acct__row-main">
                <p className="od-acct__row-title">{token.name}</p>
                <p className="od-acct__row-sub">
                  {token.token_prefix ? `${token.token_prefix}… · ` : ''}
                  created {formatWhen(token.created_at)}
                </p>
              </div>
              <button type="button" className="od-cbtn" onClick={() => handleRevoke(token.id)}>
                Revoke
              </button>
            </li>
          ))
        )}
      </ul>
    </>
  )
}

/* ------------------------------------------------------------------ shell */
