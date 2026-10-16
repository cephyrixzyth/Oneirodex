import { useEffect, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'

const ENDPOINT = '/api/admin/integrations/metadata-providers'
const FIELDS = [
  ['steam', 'Steam', 'Stage D App ID / exact title and PC enrichment. Never a download queue.'],
  ['gog', 'GOG', 'Stage D exact title and PC enrichment. DRM-free catalogue only.'],
  ['epic', 'Epic Games Store', 'Stage D exact title and PC enrichment. Ownership links only.'],
  [
    'hash_identify',
    'Hash identify',
    'Keyless console ROM identity lookup after IGDB and local DAT miss. Never enrichment or a download.',
  ],
] as const

type Providers = Record<(typeof FIELDS)[number][0], boolean>

export function MetadataProvidersSettingsPanel() {
  const [providers, setProviders] = useState<Providers | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let live = true
    getJson(ENDPOINT)
      .then((data) => {
        if (live) setProviders(data.providers as Providers)
      })
      .catch((cause) => {
        if (live) setError(errorText(cause) || 'Could not load metadata provider settings.')
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
  }, [])

  async function save() {
    if (!providers || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await putJson(ENDPOINT, { providers })
      setProviders(data.providers as Providers)
      setMessage('Metadata provider settings saved.')
    } catch (cause) {
      setError(errorText(cause) || 'Could not save metadata provider settings.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="od-admin-panel od-admin-panel--stacked"
      aria-labelledby="od-metadata-providers-title"
    >
      <h3 id="od-metadata-providers-title" className="od-admin-panel-title">
        Metadata providers
      </h3>
      <p className="od-admin-lede">
        Keyless sources used after an IGDB miss or to fill empty PC metadata. Itch.io and RAWG
        remain available for enrichment.
      </p>
      <PageStatus
        loading={loading}
        loadingMessage="Loading metadata providers…"
        error={error || null}
        announcement={message ? 'status' : undefined}
      >
        {message}
      </PageStatus>
      {providers ? (
        <fieldset className="od-admin-fieldset" disabled={busy}>
          <legend>Provider use</legend>
          {FIELDS.map(([key, label, note]) => (
            <label className="od-admin-field" key={key}>
              <input
                type="checkbox"
                checked={Boolean(providers[key])}
                onChange={(event) =>
                  setProviders((current) =>
                    current ? { ...current, [key]: event.target.checked } : current,
                  )
                }
              />
              <span>
                <strong>{label}</strong>
                <br />
                <span className="od-admin-hint">{note}</span>
              </span>
            </label>
          ))}
        </fieldset>
      ) : null}
      <div className="od-admin-actions">
        <Button
          className="od-btn--accent"
          disabled={!providers || loading || busy}
          onClick={() => void save()}
        >
          {busy ? 'Saving…' : 'Save metadata providers'}
        </Button>
      </div>
    </section>
  )
}
