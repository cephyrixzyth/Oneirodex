import { Button, Modal, PageStatus } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { ScanConflictModal } from '../components/ScanConflictModal'
import { useScanControls, type Schedule } from './useScanControls'
import './ScanControlsPage.css'

export function ScanControlsPage() {
  const {
    manualMode,
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
    browsePath,
    browseItems,
    browseBusy,
    browseError,
    browseTitleId,
    closeBrowseRef,
    conflictOpen,
    scanning,
    onConflictChoose,
    onConflictClose,
    browse,
    openBrowser,
    submit,
    invalidateManualPreview,
    listManualCandidates,
    chooseManualConflict,
    searchExistingGames,
    linkExistingGame,
    activeRoot,
    browseParts,
  } = useScanControls()
  const manualOnly = manualMode
  return (
    <Page
      title={manualMode ? 'Manual scan / identify' : 'Automatic scan'}
      lede={
        manualMode
          ? 'List game folders or files for identification without starting a scan.'
          : 'Choose a library and server folder, then start or schedule a scan.'
      }
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
      <form className="od-admin-panel od-scan-controls" onSubmit={submit}>
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
        <div className="od-scan-controls__path">
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
          <label className="od-admin-field">
            Folder inside scan location
            <input
              className="od-admin-input"
              value={folder}
              onChange={(event) => {
                invalidateManualPreview()
                setFolder(event.target.value)
              }}
              placeholder="Leave blank to scan the location root"
              disabled={scanning}
            />
          </label>
          <Button
            type="button"
            onClick={() => void openBrowser()}
            disabled={!activeRoot?.exists || !activeRoot.read || scanning}
          >
            Browse folders
          </Button>
        </div>
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
        <fieldset className="od-scan-controls__options">
          <legend>{manualOnly ? 'Manual identify options' : 'Scan options'}</legend>
          {!manualOnly ? (
            <>
              <label>
                <input
                  type="checkbox"
                  checked={removeMissing}
                  onChange={(event) => setRemoveMissing(event.target.checked)}
                  disabled={scanning}
                />{' '}
                Remove games whose files are missing
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={downloadImages}
                  onChange={(event) => setDownloadImages(event.target.checked)}
                  disabled={scanning}
                />{' '}
                Download missing images
              </label>
            </>
          ) : null}
          <label>
            <input
              type="checkbox"
              checked={updateExtras}
              onChange={(event) => setUpdateExtras(event.target.checked)}
              disabled={scanning}
            />{' '}
            Check existing games for new updates and extras
          </label>
          <label>
            <input
              type="checkbox"
              checked={fetchHltb}
              onChange={(event) => setFetchHltb(event.target.checked)}
              disabled={scanning}
            />{' '}
            Fetch HowLongToBeat data
          </label>
          <label>
            <input
              type="checkbox"
              checked={forceHltb}
              onChange={(event) => setForceHltb(event.target.checked)}
              disabled={scanning || !fetchHltb}
            />{' '}
            Refetch HowLongToBeat for existing games
          </label>
        </fieldset>
        {!manualOnly ? (
          <div className="od-scan-controls__schedule">
            <label className="od-admin-field">
              Repeat schedule
              <select
                className="od-admin-input"
                value={schedule}
                onChange={(event) => setSchedule(event.target.value as Schedule)}
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
                  onChange={(event) => setCron(event.target.value)}
                  maxLength={64}
                  placeholder="0 */6 * * *"
                  required
                  disabled={scanning}
                />
              </label>
            ) : null}
          </div>
        ) : null}
        {!manualOnly ? (
          <Button
            type="submit"
            variant="primary"
            disabled={loading || Boolean(loadError) || !libraryUuid || !rootId || scanning}
          >
            {scanning ? 'Starting scan…' : schedule ? 'Start and schedule scan' : 'Start scan'}
          </Button>
        ) : null}
      </form>
      <section
        id="manual-identify"
        className="od-admin-panel"
        aria-labelledby="od-manual-identify-title"
        hidden={!manualMode}
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
          <PageStatus
            error={manualError}
            errorMessage="Unable to list games for manual identification."
          />
        ) : null}
        {manualStatus ? <PageStatus announcement="status">{manualStatus}</PageStatus> : null}
        {manualListed && manualRows.length === 0 ? (
          <PageStatus announcement="status" className="od-admin-lede">
            No games were found in this folder.
          </PageStatus>
        ) : null}
        {manualRows.length ? (
          <div className="od-admin-table-wrap">
            <table className="od-data-table">
              <caption>Games available for manual identification</caption>
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
                        <a className="od-cbtn" href={`/add_game_manual?${params}`}>
                          Identify
                        </a>{' '}
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
      {browseOpen ? (
        <Modal
          open
          onClose={() => setBrowseOpen(false)}
          labelledBy={browseTitleId}
          initialFocusRef={closeBrowseRef}
          lockScroll
        >
          <header className="od-scan-controls__browser-head">
            <div>
              <h2 id={browseTitleId}>Choose a scan folder</h2>
              <p className="od-admin-lede">Browse folders mounted inside Oneirodex.</p>
            </div>
            <Button ref={closeBrowseRef} onClick={() => setBrowseOpen(false)}>
              Close
            </Button>
          </header>
          <nav className="od-library-browser__crumbs" aria-label="Folder path">
            <Button onClick={() => void browse('')}>{activeRoot?.path || 'Scan location'}</Button>
            {browseParts.map((part, index) => (
              <Button
                key={`${part}-${index}`}
                onClick={() => void browse(browseParts.slice(0, index + 1).join('/'))}
              >
                {part}
              </Button>
            ))}
          </nav>
          {browseError ? (
            <PageStatus error={browseError} errorMessage="Unable to browse scan folders." />
          ) : null}
          <div className="od-scan-controls__browser-list" aria-busy={browseBusy}>
            {browseBusy ? (
              <p className="od-admin-lede">Loading folders…</p>
            ) : browseItems.length ? (
              browseItems.map((item) => (
                <Button
                  key={item.name}
                  className="od-library-browser__folder"
                  onClick={() => void browse([...browseParts, item.name].join('/'))}
                >
                  {item.name}
                </Button>
              ))
            ) : (
              <p className="od-admin-lede">No folders here.</p>
            )}
          </div>
          <footer className="od-admin-panel__toolbar">
            <span className="od-admin-lede">
              {activeRoot?.path}
              {browsePath ? `/${browsePath}` : ''}
            </span>
            <Button
              variant="primary"
              onClick={() => {
                invalidateManualPreview()
                setFolder(browsePath)
                setBrowseOpen(false)
              }}
            >
              Use this folder
            </Button>
          </footer>
        </Modal>
      ) : null}
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
