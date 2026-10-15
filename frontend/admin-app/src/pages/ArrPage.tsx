import { Button, PageStatus } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { LABELS, useArrController } from './useArrController'
import './ArrPage.css'

export function ArrPage() {
  const {
    effectiveEnabled,
    envEnabled,
    moduleDraft,
    setModuleDraft,
    indexers,
    presets,
    selectedPresets,
    setSelectedPresets,
    bulkText,
    setBulkText,
    config,
    setConfig,
    secretPresence,
    connectors,
    indexerWarnings,
    query,
    setQuery,
    hits,
    searchWarnings,
    excluded,
    hardlinkDest,
    setHardlinkDest,
    proposals,
    setProposals,
    applyAllowed,
    pipelineEnabled,
    helpersEnabled,
    loading,
    loadFailed,
    busy,
    setReload,
    error,
    message,
    saveModule,
    saveConnectors,
    addIndexer,
    bulkImport,
    enablePresets,
    toggleIndexer,
    removeIndexer,
    search,
    sendToClient,
    previewHardlinks,
    applyHardlinks,
    disabled,
    URL_FIELDS,
    SECRET_FIELDS,
    USER_FIELDS,
  } = useArrController()
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
