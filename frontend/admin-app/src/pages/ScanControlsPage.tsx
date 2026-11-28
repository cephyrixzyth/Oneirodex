import { useEffect } from 'react'

import { Button, PageStatus } from '@oneirodex/ui'
import { useLocation } from 'react-router-dom'
import { AdminLink } from '../components/AdminLink'
import { Page } from '../components/Page'
import { ScanConflictModal } from '../components/ScanConflictModal'
import { ServerFolderBrowser } from '../components/ServerFolderBrowser'
import { ScanOptionsFields } from './ScanOptionsFields'
import './ScanControlsPage.css'
import { useScanControls, type Schedule } from './useScanControls'

export function ScanControlsPage() {
  const { hash, search } = useLocation()
  const activeTab = new URLSearchParams(search).get('active_tab')
  const {
    libraries,
    roots,
    libraryUuid,
    setLibraryUuid,
    rootId,
    setRootId,
    folder,
    setFolder,
    scanMode,
    setScanMode,
    removeMissing,
    setRemoveMissing,
    downloadImages,
    setDownloadImages,
    updateExtras,
    setUpdateExtras,
    fetchHltb,
    setFetchHltb,
    forceHltb,
    setForceHltb,
    recheckMatches,
    setRecheckMatches,
    retryUnmatched,
    setRetryUnmatched,
    proposeOnly,
    setProposeOnly,
    schedule,
    setSchedule,
    interval,
    setInterval,
    unit,
    setUnit,
    cron,
    setCron,
    manualRows,
    manualBusy,
    manualError,
    manualStatus,
    manualListed,
    manualConflictOpen,
    setManualConflictOpen,
    linkPath,
    setLinkPath,
    linkQuery,
    setLinkQuery,
    linkHits,
    setLinkHits,
    linkSelected,
    setLinkSelected,
    linkBusy,
    linkSearching,
    linkError,
    setLinkError,
    linkStatus,
    setLinkStatus,
    loading,
    loadError,
    setRevision,
    browseOpen,
    setBrowseOpen,
    conflictOpen,
    scanning,
    scanError,
    clearScanError,
    onConflictChoose,
    onConflictClose,
    submit,
    invalidateManualPreview,
    listManualCandidates,
    chooseManualConflict,
    searchExistingGames,
    linkExistingGame,
    activeRoot,
  } = useScanControls()
  useEffect(() => {
    // Wait for the scan controls data to settle before scrolling. The admin
    // shell is its own scroll container; while the loading state is active its
    // maximum scroll range is too short to bring Manual Identify into view.
    if (loading) return
    const sectionId = hash.slice(1) || (activeTab === 'manual' ? 'manual-identify' : '')
    if (!['automatic-scan', 'manual-identify'].includes(sectionId)) return
    const target = document.getElementById(sectionId)
    if (!target) return

    const frame = window.requestAnimationFrame(() => {
      target.scrollIntoView?.({
        block: 'start',
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      })
      target.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [activeTab, hash, loading])

  return (
    <Page
      className="od-scan-controls-page"
      title="Scan management"
      documentTitle={activeTab === 'jobs' ? 'Scan Jobs' : 'Scans'}
      lede="Start or schedule a scan, manually identify folders or files, and review scan history."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading libraries and scan locations…"
        error={loadError || null}
      />
      {loadError ? (
        <Button onClick={() => setRevision((value) => value + 1)}>
          Retry loading scan controls
        </Button>
      ) : null}
      {!loading && !loadError && libraries.length === 0 ? (
        <section
          className="od-admin-panel od-scan-controls__empty"
          aria-labelledby="scan-no-libraries"
        >
          <div>
            <h2 id="scan-no-libraries">No libraries yet</h2>
            <p>Add a library before starting automatic or manual scans.</p>
          </div>
          <AdminLink className="od-btn od-btn--secondary" to="/libraries">
            Create your first library
          </AdminLink>
        </section>
      ) : null}
      <form id="automatic-scan" className="od-admin-panel od-scan-controls" onSubmit={submit}>
        <h2>Automatic scan</h2>
        <p className="od-admin-lede">
          Choose a library and location, then start or schedule a scan.
        </p>
        {scanError ? <PageStatus error={scanError} /> : null}
        <label className="od-admin-field">
          Library
          <select
            className="od-admin-input"
            value={libraryUuid}
            onChange={(event) => {
              invalidateManualPreview()
              setLibraryUuid(event.target.value)
            }}
            required
            disabled={loading || Boolean(loadError) || scanning}
          >
            {libraries.map((library) => (
              <option key={library.uuid} value={library.uuid}>
                {library.name}
              </option>
            ))}
          </select>
        </label>
        <label className="od-admin-field">
          Game layout
          <select
            className="od-admin-input"
            value={scanMode}
            onChange={(event) => {
              invalidateManualPreview()
              setScanMode(event.target.value as typeof scanMode)
            }}
            disabled={scanning}
          >
            <option value="auto">Auto detect folders or files</option>
            <option value="folders">Game folders</option>
            <option value="files">Game files</option>
          </select>
        </label>
        <div className="od-scan-controls__root">
          <label className="od-admin-field">
            Scan location
            <select
              className="od-admin-input"
              value={rootId}
              onChange={(event) => {
                invalidateManualPreview()
                setRootId(event.target.value)
              }}
              required
              disabled={loading || scanning}
            >
              {roots.map((root) => (
                <option key={root.id} value={root.id} disabled={!root.exists || !root.read}>
                  {root.label}
                  {!root.exists || !root.read ? ' · unavailable' : ''}
                </option>
              ))}
            </select>
          </label>
          {activeRoot && (!activeRoot.exists || !activeRoot.read) ? (
            <p className="od-admin-hint od-scan-controls__root-status">
              {!activeRoot.exists ? 'Not mounted right now' : 'This location is not readable'}:{' '}
              {activeRoot.path}
            </p>
          ) : null}
        </div>
        <div className="od-admin-field od-scan-controls__folder">
          <label htmlFor="od-scan-folder">Folder inside scan location</label>
          <div className="od-scan-controls__folder-row">
            <input
              id="od-scan-folder"
              className="od-admin-input"
              value={folder}
              onChange={(event) => {
                invalidateManualPreview()
                setFolder(event.target.value)
              }}
              placeholder="Leave blank to scan the location root"
              disabled={scanning}
            />
            <Button
              type="button"
              className="od-btn--secondary"
              onClick={() => setBrowseOpen(true)}
              disabled={!activeRoot?.exists || !activeRoot.read || scanning}
            >
              Browse folders
            </Button>
          </div>
        </div>
        <ScanOptionsFields
          disabled={scanning}
          {...{ retryUnmatched, setRetryUnmatched, recheckMatches, setRecheckMatches }}
          {...{ proposeOnly, setProposeOnly, removeMissing, setRemoveMissing }}
          {...{ downloadImages, setDownloadImages, updateExtras, setUpdateExtras }}
          {...{ fetchHltb, setFetchHltb, forceHltb, setForceHltb }}
        />
        <div className="od-scan-controls__schedule">
          <label className="od-admin-field">
            Repeat schedule
            <select
              className="od-admin-input"
              value={schedule}
              onChange={(event) => {
                clearScanError()
                setSchedule(event.target.value as Schedule)
              }}
              disabled={scanning}
            >
              <option value="">Once (no repeat)</option>
              <option value="8_hours">Every 8 hours</option>
              <option value="24_hours">Every 24 hours</option>
              <option value="48_hours">Every 48 hours</option>
              <option value="interval">Every N minutes or hours</option>
              <option value="cron">Cron expression (UTC)</option>
            </select>
          </label>
          {schedule === 'interval' ? (
            <div className="od-scan-controls__interval">
              <label className="od-admin-field">
                Interval
                <input
                  className="od-admin-input"
                  type="number"
                  min={1}
                  max={10080}
                  value={interval}
                  onChange={(event) => setInterval(Number(event.target.value))}
                  disabled={scanning}
                />
              </label>
              <label className="od-admin-field">
                Unit
                <select
                  className="od-admin-input"
                  value={unit}
                  onChange={(event) => setUnit(event.target.value as typeof unit)}
                  disabled={scanning}
                >
                  <option value="hours">Hours</option>
                  <option value="minutes">Minutes</option>
                </select>
              </label>
            </div>
          ) : null}
          {schedule === 'cron' ? (
            <label className="od-admin-field">
              Cron expression (UTC)
              <input
                className="od-admin-input"
                value={cron}
                onChange={(event) => {
                  clearScanError()
                  setCron(event.target.value)
                }}
                maxLength={64}
                placeholder="0 */6 * * *"
                required
                disabled={scanning}
              />
            </label>
          ) : null}
        </div>
        <div className="od-scan-controls__actions">
          <Button
            type="submit"
            variant="primary"
            disabled={loading || Boolean(loadError) || !libraryUuid || !rootId || scanning}
          >
            {scanning ? 'Starting scan…' : schedule ? 'Start and schedule scan' : 'Start scan'}
          </Button>
        </div>
      </form>
      <section
        id="manual-identify"
        className="od-admin-panel od-scan-controls__manual"
        tabIndex={-1}
        aria-labelledby="od-manual-identify-title"
      >
        <h2 id="od-manual-identify-title">Manual identify</h2>
        <p className="od-admin-lede">
          When no scan is running, list folders or supported game files to identify. If a scan is
          already running, this action queues the manual scan using the selected scan options.
        </p>
        <Button
          type="button"
          onClick={() => void listManualCandidates()}
          disabled={loading || Boolean(loadError) || !libraryUuid || !rootId || manualBusy}
        >
          {manualBusy ? 'Listing games…' : 'List games to identify'}
        </Button>
        {manualError ? (
          <>
            <PageStatus error={manualError} />
            {manualError.toLowerCase().includes('write permissions') ? (
              <p className="od-admin-hint">
                Manual identification needs write access to the selected game folders when local
                metadata files are enabled. Grant Oneirodex write access or turn off “Write metadata
                file on manual ID” in Server Settings.{' '}
                <AdminLink to="/admin/new_server_settings">Open Server Settings</AdminLink>
              </p>
            ) : null}
          </>
        ) : null}
        {manualStatus ? <PageStatus announcement="status">{manualStatus}</PageStatus> : null}
        {manualListed && manualRows.length === 0 ? (
          <PageStatus announcement="status" className="od-admin-lede">
            No games were found in this folder.
          </PageStatus>
        ) : null}
        {manualRows.length ? (
          <div
            className="od-admin-table-wrap od-scan-controls__manual-results"
            role="region"
            tabIndex={0}
            aria-label="Manual identification candidates; scroll horizontally to see all columns"
          >
            <table className="od-data-table">
              <caption className="od-scan-controls__manual-caption">
                Games available for manual identification
              </caption>
              <thead>
                <tr>
                  <th scope="col">Game name</th>
                  <th scope="col">Location</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {manualRows.map((row) => {
                  const params = new URLSearchParams({
                    full_disk_path: row.full_path,
                    library_uuid: libraryUuid,
                  })
                  return (
                    <tr key={row.full_path}>
                      <th scope="row">{row.name}</th>
                      <td>
                        <span title={row.full_path}>{row.full_path}</span>
                      </td>
                      <td>
                        <AdminLink className="od-cbtn" to={`/add_game_manual?${params}`}>
                          Identify
                        </AdminLink>{' '}
                        <Button
                          type="button"
                          className="od-btn--secondary"
                          onClick={() => {
                            setLinkPath(row.full_path)
                            setLinkQuery(row.name)
                            setLinkHits([])
                            setLinkSelected(null)
                            setLinkError('')
                            setLinkStatus('')
                          }}
                          disabled={Boolean(linkPath) || linkBusy}
                        >
                          Link existing game
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
        {linkPath ? (
          <div className="od-admin-panel" aria-labelledby="od-link-existing-title">
            <h3 id="od-link-existing-title" className="od-admin-panel-title">
              Link folder to an existing game
            </h3>
            <p className="od-admin-lede">
              Selected folder: <code>{linkPath}</code>
            </p>
            <div className="od-admin-panel__toolbar">
              <label className="od-admin-field">
                Search existing games
                <input
                  className="od-admin-input"
                  value={linkQuery}
                  onChange={(event) => {
                    setLinkQuery(event.target.value)
                    setLinkHits([])
                    setLinkSelected(null)
                    setLinkStatus('')
                  }}
                  disabled={linkSearching || linkBusy}
                  maxLength={100}
                />
              </label>
              <Button
                type="button"
                className="od-btn--secondary"
                onClick={() => void searchExistingGames()}
                disabled={!linkQuery.trim() || linkSearching || linkBusy}
              >
                {linkSearching ? 'Searching…' : 'Search existing games'}
              </Button>
            </div>
            {linkError ? (
              <PageStatus error={linkError} errorMessage="Unable to link this folder." />
            ) : null}
            {linkStatus ? <PageStatus announcement="status">{linkStatus}</PageStatus> : null}
            {linkHits.length ? (
              <div role="group" aria-label="Existing game search results">
                {linkHits.map((game) => (
                  <Button
                    key={game.uuid}
                    type="button"
                    className={
                      linkSelected?.uuid === game.uuid ? 'od-btn--accent' : 'od-btn--secondary'
                    }
                    aria-pressed={linkSelected?.uuid === game.uuid}
                    onClick={() => setLinkSelected(game)}
                    disabled={linkBusy}
                  >
                    {game.name}
                    {game.full_disk_path ? ` · ${game.full_disk_path}` : ''}
                  </Button>
                ))}
              </div>
            ) : null}
            <div className="od-admin-panel__toolbar">
              <Button
                type="button"
                variant="primary"
                onClick={() => void linkExistingGame()}
                disabled={!linkSelected || linkBusy}
              >
                {linkBusy ? 'Linking…' : 'Link selected game'}
              </Button>
              <Button
                type="button"
                className="od-btn--secondary"
                onClick={() => {
                  setLinkPath('')
                  setLinkHits([])
                  setLinkSelected(null)
                  setLinkError('')
                  setLinkStatus('')
                }}
                disabled={linkBusy}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
        {!linkPath && linkStatus ? (
          <PageStatus announcement="status">{linkStatus}</PageStatus>
        ) : null}
      </section>
      <ServerFolderBrowser
        open={browseOpen}
        onClose={() => setBrowseOpen(false)}
        title="Choose a scan folder"
        initialRootId={rootId}
        initialPath={folder}
        onSelect={({ root, relativePath }) => {
          invalidateManualPreview()
          setRootId(root.id)
          setFolder(relativePath)
        }}
      />
      <ScanConflictModal
        open={conflictOpen}
        busy={scanning}
        onChoose={onConflictChoose}
        onClose={onConflictClose}
      />
      <ScanConflictModal
        open={manualConflictOpen}
        busy={manualBusy}
        onChoose={chooseManualConflict}
        onClose={() => {
          if (!manualBusy) setManualConflictOpen(false)
        }}
        title="Scan in progress"
        lede="A scan is already running. List games when it finishes, queue this manual scan, or force a parallel scan."
      />
    </Page>
  )
}
