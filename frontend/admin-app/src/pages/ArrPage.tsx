import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { deleteJson, getJson, postJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import './ArrPage.css'

type Indexer = {
  id: string
  name: string
  protocol: string
  url: string
  ready: boolean
  enabled: boolean
  source: string
  api_key_set?: boolean
}
type Preset = { id: string; name: string; protocol?: string; notes?: string }
type Hit = {
  title: string
  indexer?: string
  seeders?: number
  size?: number
  download_url?: string
  quality?: { score?: number; allowed?: boolean; reasons?: string[] }
}
type Proposal = {
  name?: string
  source?: string
  dest?: string
  preview?: { would_succeed?: boolean; reasons?: string[] }
}
type Config = Record<string, string>
const URL_FIELDS = [
  'prowlarr_url',
  'jackett_url',
  'qbittorrent_url',
  'transmission_url',
  'sabnzbd_url',
  'nzbget_url',
] as const
const SECRET_FIELDS = [
  'prowlarr_api_key',
  'jackett_api_key',
  'qbittorrent_password',
  'transmission_password',
  'sabnzbd_api_key',
  'nzbget_password',
] as const
const USER_FIELDS = ['qbittorrent_username', 'transmission_username', 'nzbget_username'] as const
const LABELS: Record<string, string> = {
  prowlarr_url: 'Prowlarr URL',
  jackett_url: 'Jackett URL',
  qbittorrent_url: 'qBittorrent URL',
  transmission_url: 'Transmission URL',
  sabnzbd_url: 'SABnzbd URL',
  nzbget_url: 'NZBGet URL',
  qbittorrent_username: 'qBittorrent username',
  transmission_username: 'Transmission username',
  nzbget_username: 'NZBGet username',
  prowlarr_api_key: 'Prowlarr API key',
  jackett_api_key: 'Jackett API key',
  qbittorrent_password: 'qBittorrent password',
  transmission_password: 'Transmission password',
  sabnzbd_api_key: 'SABnzbd API key',
  nzbget_password: 'NZBGet password',
}

function arrConfig(data: any): { draft: Config; secrets: Record<string, boolean> } {
  if (!data || URL_FIELDS.some((key) => typeof data[key] !== 'string'))
    throw new Error('Arr connector settings returned an invalid response.')
  const draft: Config = {}
  const secrets: Record<string, boolean> = {}
  for (const key of URL_FIELDS) draft[key] = data[key] || ''
  for (const key of USER_FIELDS) draft[key] = typeof data[key] === 'string' ? data[key] : ''
  for (const key of SECRET_FIELDS) {
    const presenceKey = key.endsWith('_api_key')
      ? `${key}_set`
      : `${key.replace(/_password$/, '')}_password_set`
    secrets[key] = Boolean(data[presenceKey])
    draft[key] = ''
  }
  return { draft, secrets }
}

export function ArrPage() {
  const [effectiveEnabled, setEffectiveEnabled] = useState(false)
  const [envEnabled, setEnvEnabled] = useState(false)
  const [moduleDraft, setModuleDraft] = useState(false)
  const [indexers, setIndexers] = useState<Indexer[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [selectedPresets, setSelectedPresets] = useState<string[]>([])
  const [bulkText, setBulkText] = useState('')
  const [config, setConfig] = useState<Config>({})
  const [secretPresence, setSecretPresence] = useState<Record<string, boolean>>({})
  const [connectors, setConnectors] = useState<any[]>([])
  const [indexerWarnings, setIndexerWarnings] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<Hit[]>([])
  const [searchWarnings, setSearchWarnings] = useState<string[]>([])
  const [excluded, setExcluded] = useState(0)
  const [hardlinkDest, setHardlinkDest] = useState('')
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [applyAllowed, setApplyAllowed] = useState(false)
  const [pipelineEnabled, setPipelineEnabled] = useState(false)
  const [helpersEnabled, setHelpersEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson('/api/arr/module')
      .then(async (module: any) => {
        if (
          !module ||
          typeof module.enabled !== 'boolean' ||
          typeof module.db_enabled !== 'boolean' ||
          typeof module.env_enabled !== 'boolean'
        )
          throw new Error('Arr module status returned an invalid response.')
        if (cancelled) return
        setEffectiveEnabled(module.enabled)
        setModuleDraft(module.db_enabled)
        setEnvEnabled(module.env_enabled)
        if (!module.enabled) return
        const [status, indexerData, configData] = await Promise.all([
          getJson('/api/arr/status'),
          getJson('/api/arr/indexers'),
          getJson('/api/arr/config'),
        ])
        if (cancelled) return
        if (
          !Array.isArray(status?.connectors) ||
          !Array.isArray(indexerData?.indexers) ||
          !Array.isArray(indexerData?.presets)
        )
          throw new Error('Arr module returned an invalid connector or indexer list.')
        const next = arrConfig(configData)
        setConnectors(status.connectors)
        setIndexerWarnings(Array.isArray(status.indexer_warnings) ? status.indexer_warnings : [])
        setPipelineEnabled(Boolean(status.hardlink_pipeline_enabled))
        setHelpersEnabled(Boolean(status.hardlink_helpers_enabled))
        setApplyAllowed(Boolean(status.hardlink_apply_allowed))
        setIndexers(indexerData.indexers)
        setPresets(indexerData.presets)
        setConfig(next.draft)
        setSecretPresence(next.secrets)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err) || 'Unable to load Arr settings.')
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

  function begin(label: string) {
    if (loading || loadFailed || busy) return false
    setBusy(true)
    setError('')
    setMessage('')
    if (label) setMessage(label)
    return true
  }
  function end() {
    setBusy(false)
  }

  async function saveModule(event: FormEvent) {
    event.preventDefault()
    if (!begin('Saving module preference…')) return
    try {
      const data = await putJson('/api/arr/module', { enabled: moduleDraft })
      setEffectiveEnabled(Boolean(data.enabled))
      setEnvEnabled(Boolean(data.env_enabled))
      setMessage(`Saved. Effective status: ${data.enabled ? 'on' : 'off'}.`)
      setReload((value) => value + 1)
    } catch (err) {
      setError(errorText(err) || 'Unable to save Arr module preference.')
    } finally {
      end()
    }
  }

  async function saveConnectors(event: FormEvent) {
    event.preventDefault()
    if (!begin('Saving connector settings…')) return
    const body: Config = { ...config }
    for (const key of SECRET_FIELDS) {
      if (!config[key]?.trim()) delete body[key]
    }
    try {
      const data = await putJson('/api/arr/config', body)
      const next = arrConfig(data.config)
      setConfig(next.draft)
      setSecretPresence(next.secrets)
      setMessage('Connector settings saved. Blank secret fields kept their saved values.')
    } catch (err) {
      setError(errorText(err) || 'Unable to save connector settings.')
    } finally {
      end()
    }
  }

  async function refreshIndexers() {
    const data = await getJson('/api/arr/indexers')
    if (!Array.isArray(data?.indexers) || !Array.isArray(data?.presets))
      throw new Error('Indexer registry returned an invalid response.')
    setIndexers(data.indexers)
    setPresets(data.presets)
  }

  async function addIndexer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const fd = new FormData(form)
    if (!begin('Adding indexer…')) return
    try {
      await postJson('/api/arr/indexers', {
        name: fd.get('name'),
        protocol: fd.get('protocol'),
        url: fd.get('url'),
        api_key: fd.get('api_key'),
        enabled: true,
      })
      form.reset()
      await refreshIndexers()
      setMessage('Indexer added.')
    } catch (err) {
      setError(errorText(err) || 'Unable to add indexer.')
    } finally {
      end()
    }
  }

  async function bulkImport() {
    const raw = bulkText.trim()
    if (!raw) {
      setError('Paste JSON or CSV first.')
      return
    }
    let body: unknown
    try {
      body = JSON.parse(raw)
    } catch {
      body = { text: raw }
    }
    if (!begin('Importing indexers…')) return
    try {
      const result = await postJson('/api/arr/indexers/bulk', body)
      setBulkText('')
      await refreshIndexers()
      setMessage(`Imported ${result.count || 0} indexer(s).`)
    } catch (err) {
      setError(errorText(err) || 'Unable to import indexers.')
    } finally {
      end()
    }
  }

  async function enablePresets() {
    if (!selectedPresets.length) {
      setError('Select at least one preset.')
      return
    }
    if (!begin('Enabling selected presets…')) return
    try {
      const result = await postJson('/api/arr/indexers/enable-presets', {
        preset_ids: selectedPresets,
      })
      setSelectedPresets([])
      await refreshIndexers()
      setMessage(
        `Enabled ${result.count || 0} preset(s). Add real URLs and API keys before searching.`,
      )
    } catch (err) {
      setError(errorText(err) || 'Unable to enable presets.')
    } finally {
      end()
    }
  }

  async function toggleIndexer(row: Indexer, enabled: boolean) {
    if (!begin('Updating indexer…')) return
    try {
      await putJson(`/api/arr/indexers/${encodeURIComponent(row.id)}`, { enabled })
      await refreshIndexers()
      setMessage('Indexer updated.')
    } catch (err) {
      setError(errorText(err) || 'Unable to update indexer.')
    } finally {
      end()
    }
  }

  async function removeIndexer(row: Indexer) {
    if (
      !(await confirmAction({
        title: `Delete ${row.name}?`,
        body: 'This removes the indexer from the native registry.',
        confirmLabel: 'Delete indexer',
        tone: 'danger',
      }))
    )
      return
    if (!begin('Deleting indexer…')) return
    try {
      await deleteJson(`/api/arr/indexers/${encodeURIComponent(row.id)}`)
      await refreshIndexers()
      setMessage('Indexer deleted.')
    } catch (err) {
      setError(errorText(err) || 'Unable to delete indexer.')
    } finally {
      end()
    }
  }

  async function search() {
    const term = query.trim()
    if (!term) {
      setError('Enter a title to search.')
      return
    }
    if (!begin('Searching configured indexers…')) return
    try {
      const data = await getJson(`/api/arr/search?q=${encodeURIComponent(term)}`)
      if (!Array.isArray(data.results))
        throw new Error('Indexer search returned an invalid result list.')
      setHits(data.results)
      setSearchWarnings(Array.isArray(data.warnings) ? data.warnings : [])
      setExcluded(Number(data.excluded_by_quality) || 0)
      setMessage(
        data.results.length
          ? `${data.results.length} result(s) found.`
          : 'No results matched the active quality profile.',
      )
    } catch (err) {
      setError(errorText(err) || 'Indexer search failed.')
    } finally {
      end()
    }
  }

  async function sendToClient(hit: Hit) {
    if (!hit.download_url) {
      setError('This result does not include a download link.')
      return
    }
    if (
      !(await confirmAction({
        title: 'Send this result to qBittorrent?',
        body: `This contacts your configured download client and adds “${hit.title}” to its queue. Review the result and your ownership rights first.`,
        confirmLabel: 'Add to qBittorrent',
      }))
    )
      return
    if (!begin('Sending result to qBittorrent…')) return
    try {
      await postJson('/api/arr/download', { download_url: hit.download_url })
      setMessage('Result sent to qBittorrent.')
    } catch (err) {
      setError(errorText(err) || 'Unable to send result to qBittorrent.')
    } finally {
      end()
    }
  }

  async function previewHardlinks() {
    const dest = hardlinkDest.trim()
    if (!dest) {
      setError('Choose an existing library destination directory.')
      return
    }
    if (!begin('Previewing completed downloads…')) return
    try {
      const data = await postJson('/api/arr/hardlink/preview', { library_dest_dir: dest })
      if (!Array.isArray(data.proposals))
        throw new Error('Hardlink preview returned an invalid proposal list.')
      setProposals(data.proposals)
      setApplyAllowed(Boolean(data.apply_allowed))
      setMessage(
        `${data.count || data.proposals.length} completed download(s) previewed. No files were changed.`,
      )
    } catch (err) {
      setError(errorText(err) || 'Unable to preview hardlinks.')
    } finally {
      end()
    }
  }

  async function applyHardlinks() {
    const safeCount = proposals.filter((item) => item.preview?.would_succeed).length
    if (!safeCount) {
      setError('Preview must contain at least one allowed proposal before applying.')
      return
    }
    if (!applyAllowed) {
      setError('Hardlink apply is disabled by the current environment gates.')
      return
    }
    if (
      !(await confirmAction({
        title: `Create ${safeCount} hardlink${safeCount === 1 ? '' : 's'}?`,
        body: 'This writes links into the selected library folder. Only previewed, successful proposals will be applied; verify every source and destination before continuing.',
        confirmLabel: 'Apply hardlinks',
        tone: 'danger',
      }))
    )
      return
    if (!begin('Applying previewed hardlinks…')) return
    try {
      const result = await postJson('/api/arr/hardlink/apply', { proposals, only_ok: true })
      setProposals([])
      setMessage(
        `Hardlink operation finished: ${result.applied?.length || 0} applied, ${result.skipped?.length || 0} skipped.`,
      )
    } catch (err) {
      setError(errorText(err) || 'Unable to apply hardlinks.')
    } finally {
      end()
    }
  }

  const disabled = loading || loadFailed || busy
  return (
    <Page
      title="Arr module"
      lede="Bring your own Torznab/Newznab indexers and optional Prowlarr/Jackett hubs. This module does not install or download DRM store titles."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading Arr settings…"
        error={loadFailed ? error : null}
      />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>Retry loading Arr settings</Button>
      ) : null}
      {error && !loadFailed ? (
        <PageStatus announcement="alert" className="od-arr__error">
          {error}
        </PageStatus>
      ) : null}
      {message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      <form className="od-admin-panel od-arr__panel" onSubmit={saveModule}>
        <h2>Module enable</h2>
        <p className="od-admin-hint">
          Enable here or with <code>ENABLE_ARR_MODULE=true</code>. Environment status:{' '}
          <strong>{envEnabled ? 'on' : 'off'}</strong>.
        </p>
        <label className="od-admin-check">
          <input
            type="checkbox"
            checked={moduleDraft}
            disabled={disabled}
            onChange={(event) => setModuleDraft(event.target.checked)}
          />{' '}
          Enable Arr module (admin setting)
        </label>
        <Button variant="primary" type="submit" disabled={disabled}>
          {busy ? 'Working…' : 'Save enable'}
        </Button>
        <p className="od-admin-hint">
          Effective status: <strong>{effectiveEnabled ? 'on' : 'off'}</strong>
        </p>
      </form>
      {effectiveEnabled ? (
        <>
          <section
            className="od-admin-panel od-arr__panel"
            aria-labelledby="od-arr-connectors-title"
          >
            <h2 id="od-arr-connectors-title">Connector status</h2>
            {connectors.length ? (
              <ul className="od-arr__connector-list">
                {connectors.map((item) => (
                  <li key={item.id}>
                    <strong>{item.id}</strong>: {item.configured ? 'configured' : 'not configured'}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="od-admin-hint">No connector status is available.</p>
            )}
            {indexerWarnings.length ? (
              <PageStatus announcement="status" className="od-arr__warning">
                Indexer warnings: {indexerWarnings.join(' · ')}
              </PageStatus>
            ) : null}
          </section>
          <section className="od-admin-panel od-arr__panel" aria-labelledby="od-arr-indexer-title">
            <h2 id="od-arr-indexer-title">Native indexers</h2>
            <p className="od-admin-hint">
              API keys are never returned by the server. Native indexer URLs cannot target private
              LAN addresses.
            </p>
            <div className="od-admin-table-wrap">
              <table className="od-data-table">
                <caption>Configured native indexers</caption>
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Protocol</th>
                    <th scope="col">URL</th>
                    <th scope="col">Ready</th>
                    <th scope="col">Enabled</th>
                    <th scope="col">Source</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {indexers.length ? (
                    indexers.map((row) => (
                      <tr key={row.id}>
                        <th scope="row">{row.name}</th>
                        <td>{row.protocol}</td>
                        <td className="od-arr__url">{row.url}</td>
                        <td>{row.ready ? 'Yes' : 'No'}</td>
                        <td>
                          <label className="od-admin-check">
                            <input
                              type="checkbox"
                              checked={row.enabled}
                              disabled={disabled}
                              onChange={(event) => void toggleIndexer(row, event.target.checked)}
                            />{' '}
                            Enabled
                          </label>
                        </td>
                        <td>{row.source || 'manual'}</td>
                        <td>
                          <Button
                            variant="danger"
                            disabled={disabled}
                            onClick={() => void removeIndexer(row)}
                          >
                            Delete {row.name}
                          </Button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={7}>
                        No native indexers yet. Add one, import, or enable presets.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <form className="od-arr__form-grid" onSubmit={(event) => void addIndexer(event)}>
              <h3>Add one</h3>
              <label className="od-admin-field">
                Name
                <input
                  className="od-admin-input"
                  name="name"
                  required
                  maxLength={120}
                  disabled={disabled}
                  placeholder="My indexer"
                />
              </label>
              <label className="od-admin-field">
                Protocol
                <select className="od-admin-input" name="protocol" disabled={disabled}>
                  <option value="torznab">Torznab</option>
                  <option value="newznab">Newznab</option>
                </select>
              </label>
              <label className="od-admin-field">
                URL
                <input
                  className="od-admin-input"
                  name="url"
                  type="url"
                  required
                  disabled={disabled}
                  placeholder="https://…/api"
                />
              </label>
              <label className="od-admin-field">
                API key
                <input
                  className="od-admin-input"
                  name="api_key"
                  type="password"
                  autoComplete="new-password"
                  disabled={disabled}
                />
              </label>
              <Button variant="primary" type="submit" disabled={disabled}>
                Add indexer
              </Button>
            </form>
            <label className="od-admin-field">
              Bulk import (JSON array/object or CSV)
              <textarea
                className="od-admin-input od-arr__bulk"
                value={bulkText}
                onChange={(event) => setBulkText(event.target.value)}
                disabled={disabled}
                rows={4}
                placeholder={'[{"name":"…","protocol":"torznab","url":"https://…","api_key":"…"}]'}
              />
            </label>
            <Button disabled={disabled} onClick={() => void bulkImport()}>
              Import indexers
            </Button>
            <h3>Presets</h3>
            <p className="od-admin-hint">
              Curated templates contain no secrets. Enabling a preset copies it into your registry;
              configure a real URL and key before search.
            </p>
            {presets.length ? (
              <fieldset className="od-arr__presets" disabled={disabled}>
                <legend>Choose indexer presets</legend>
                {presets.map((preset) => (
                  <label className="od-admin-check" key={preset.id}>
                    <input
                      type="checkbox"
                      checked={selectedPresets.includes(preset.id)}
                      onChange={(event) =>
                        setSelectedPresets((values) =>
                          event.target.checked
                            ? [...values, preset.id]
                            : values.filter((id) => id !== preset.id),
                        )
                      }
                    />{' '}
                    {preset.name} ({preset.protocol || 'torznab'})
                  </label>
                ))}
              </fieldset>
            ) : (
              <p className="od-admin-hint">No presets are available.</p>
            )}
            <Button
              disabled={disabled || !selectedPresets.length}
              onClick={() => void enablePresets()}
            >
              Enable selected presets
            </Button>
          </section>
          <form
            className="od-admin-panel od-arr__panel od-arr__form-grid"
            onSubmit={saveConnectors}
          >
            <h2>Hubs and download clients</h2>
            {[...URL_FIELDS, ...USER_FIELDS, ...SECRET_FIELDS].map((key) => (
              <label className="od-admin-field" key={key}>
                {LABELS[key]}
                {URL_FIELDS.includes(key as (typeof URL_FIELDS)[number]) ? (
                  <input
                    className="od-admin-input"
                    type="url"
                    value={config[key] || ''}
                    disabled={disabled}
                    onChange={(event) =>
                      setConfig((values) => ({ ...values, [key]: event.target.value }))
                    }
                    placeholder={key.includes('url') ? 'http://host:port' : ''}
                  />
                ) : (
                  <input
                    className="od-admin-input"
                    type={
                      SECRET_FIELDS.includes(key as (typeof SECRET_FIELDS)[number])
                        ? 'password'
                        : 'text'
                    }
                    autoComplete="off"
                    value={config[key] || ''}
                    disabled={disabled}
                    onChange={(event) =>
                      setConfig((values) => ({ ...values, [key]: event.target.value }))
                    }
                    placeholder={
                      SECRET_FIELDS.includes(key as (typeof SECRET_FIELDS)[number])
                        ? secretPresence[key]
                          ? 'Saved — leave blank to keep'
                          : 'Not configured'
                        : ''
                    }
                  />
                )}
              </label>
            ))}
            <p className="od-admin-hint">
              Secret fields are write-only. Leaving a saved secret blank preserves it.
            </p>
            <Button variant="primary" type="submit" disabled={disabled}>
              {busy ? 'Working…' : 'Save connector settings'}
            </Button>
          </form>
          <section className="od-admin-panel od-arr__panel" aria-labelledby="od-arr-search-title">
            <h2 id="od-arr-search-title">Search indexers</h2>
            <form
              className="od-arr__search"
              onSubmit={(event) => {
                event.preventDefault()
                void search()
              }}
            >
              <label className="od-admin-field">
                Game title
                <input
                  className="od-admin-input"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  disabled={disabled}
                  placeholder="Search title"
                />
              </label>
              <Button variant="primary" type="submit" disabled={disabled}>
                {busy ? 'Searching…' : 'Search'}
              </Button>
            </form>
            {searchWarnings.length ? (
              <PageStatus announcement="status" className="od-arr__warning">
                Search warnings: {searchWarnings.join(' · ')}
              </PageStatus>
            ) : null}
            {excluded ? (
              <p className="od-admin-hint">
                {excluded} result(s) were excluded by the active quality profile.
              </p>
            ) : null}
            {hits.length ? (
              <div className="od-admin-table-wrap">
                <table className="od-data-table">
                  <caption>Search results</caption>
                  <thead>
                    <tr>
                      <th scope="col">Title</th>
                      <th scope="col">Indexer</th>
                      <th scope="col">Quality</th>
                      <th scope="col">Seeders</th>
                      <th scope="col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hits.map((hit, index) => (
                      <tr key={`${hit.title}-${hit.indexer}-${index}`}>
                        <th scope="row">{hit.title}</th>
                        <td>{hit.indexer || '—'}</td>
                        <td>
                          {hit.quality?.score ?? '—'}
                          {hit.quality?.allowed === false ? ' · blocked by profile' : ''}
                        </td>
                        <td>{hit.seeders ?? '—'}</td>
                        <td>
                          <Button
                            disabled={disabled || !hit.download_url}
                            onClick={() => void sendToClient(hit)}
                          >
                            Send to qBittorrent…
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : query && !busy ? (
              <p className="od-admin-hint">
                No results shown. Search to see configured indexer results.
              </p>
            ) : null}
          </section>
          <section className="od-admin-panel od-arr__panel" aria-labelledby="od-arr-hardlink-title">
            <h2 id="od-arr-hardlink-title">Hardlink pipeline</h2>
            <p className="od-admin-hint">
              Preview completed qBittorrent downloads in a library folder. Preview is read-only;
              Apply requires the pipeline, helper and apply gates.
            </p>
            <p className="od-admin-hint">
              Pipeline: {pipelineEnabled ? 'on' : 'off'} · Hardlink helpers:{' '}
              {helpersEnabled ? 'on' : 'off'} · Apply: {applyAllowed ? 'allowed' : 'off'}
            </p>
            <label className="od-admin-field">
              Library destination directory
              <input
                className="od-admin-input"
                value={hardlinkDest}
                onChange={(event) => {
                  setHardlinkDest(event.target.value)
                  setProposals([])
                }}
                disabled={disabled}
                placeholder="/storage/games/Library"
              />
            </label>
            <div className="od-admin-actions-row">
              <Button
                disabled={disabled || !pipelineEnabled || !helpersEnabled}
                onClick={() => void previewHardlinks()}
              >
                Preview hardlinks
              </Button>
              <Button
                variant="danger"
                disabled={disabled || !proposals.length || !applyAllowed}
                onClick={() => void applyHardlinks()}
              >
                Apply allowed proposals…
              </Button>
            </div>
            {proposals.length ? (
              <div className="od-admin-table-wrap">
                <table className="od-data-table">
                  <caption>Read-only hardlink preview</caption>
                  <thead>
                    <tr>
                      <th scope="col">Download</th>
                      <th scope="col">Source</th>
                      <th scope="col">Destination</th>
                      <th scope="col">Preview</th>
                    </tr>
                  </thead>
                  <tbody>
                    {proposals.map((item, index) => (
                      <tr key={`${item.name}-${index}`}>
                        <th scope="row">{item.name || `Download ${index + 1}`}</th>
                        <td className="od-arr__url">{item.source || '—'}</td>
                        <td className="od-arr__url">{item.dest || '—'}</td>
                        <td>
                          {item.preview?.would_succeed
                            ? 'Ready'
                            : (item.preview?.reasons || ['Not ready']).join('; ')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {!applyAllowed ? (
              <p className="od-arr__warning" role="note">
                Hardlink apply is disabled by environment safety gates. No files will be changed
                from this page.
              </p>
            ) : null}
          </section>
        </>
      ) : (
        <section className="od-admin-panel" aria-live="polite">
          <h2>Module disabled</h2>
          <p>
            Enable the module above or set <code>ENABLE_ARR_MODULE=true</code> in the environment.
          </p>
        </section>
      )}
      <a className="od-admin-backlink" href="/admin/settings">
        Back to Settings
      </a>
    </Page>
  )
}
