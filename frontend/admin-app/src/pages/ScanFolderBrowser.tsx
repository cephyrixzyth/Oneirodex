import { Button, Modal, PageStatus } from '@oneirodex/ui'
import type { useScanControls } from './useScanControls'
type Props = Pick<
  ReturnType<typeof useScanControls>,
  | 'browseOpen'
  | 'setBrowseOpen'
  | 'browseTitleId'
  | 'closeBrowseRef'
  | 'browse'
  | 'activeRoot'
  | 'browseParts'
  | 'browseError'
  | 'browseBusy'
  | 'browseItems'
  | 'browsePath'
  | 'invalidateManualPreview'
  | 'setFolder'
>
export function ScanFolderBrowser({
  browseOpen,
  setBrowseOpen,
  browseTitleId,
  closeBrowseRef,
  browse,
  activeRoot,
  browseParts,
  browseError,
  browseBusy,
  browseItems,
  browsePath,
  invalidateManualPreview,
  setFolder,
}: Props) {
  return browseOpen ? (
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
  ) : null
}
