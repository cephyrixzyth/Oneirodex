import { Button, PageStatus } from '@oneirodex/ui'
import { postJson } from '../api/adminApi'
import { AdminPageActions } from '../components/AdminPageActions'
import { OpenPathModal } from '../components/OpenPathModal'
import { Page } from '../components/Page'
import { ScanUnmatchedFilters } from './ScanUnmatchedFilters'
import './ScanUnmatchedPage.css'
import { ScanUnmatchedTable } from './ScanUnmatchedTable'
import { useScanUnmatchedActions } from './useScanUnmatchedActions'
import { useScanUnmatchedData } from './useScanUnmatchedData'
export function ScanUnmatchedPage() {
  const data = useScanUnmatchedData()
  const actions = useScanUnmatchedActions(data)
  const model = { ...data, ...actions }
  const {
    linkSuccess,
    loading,
    error,
    setError,
    status,
    libraryUuid,
    platform,
    region,
    searchQuery,
    why,
    kind,
    pathModal,
    setPathModal,
    actionStatus,
    setActionStatus,
    selectedIds,
    setSelectedIds,
    selectedRows,
    setReloadKey,
    runBatchAction,
    clearRows,
  } = model

  return (
    <Page
      title="Unmatched folders"
      lede="Review unmatched folders and duplicate candidates from scan management."
      className="od-scan-unmatched-page"
    >
      <AdminPageActions label="Unmatched folder actions">
        <Button className="od-cbtn" disabled={loading} onClick={() => void clearRows('Unmatched')}>
          Clear Unmatched
        </Button>
        <Button className="od-cbtn" disabled={loading} onClick={() => void clearRows('all')}>
          Clear All
        </Button>
        <Button
          className="od-cbtn"
          disabled={loading}
          onClick={async () => {
            try {
              const result = await postJson('/api/unmatched_folders/reclassify_duplicates', {})
              setActionStatus(`Fixed ${Number(result.changed_count) || 0} false duplicates.`)
              setReloadKey((value) => value + 1)
            } catch (reason) {
              setError(reason)
            }
          }}
        >
          Fix false duplicates
        </Button>
        <Button
          className="od-cbtn"
          disabled={loading}
          onClick={async () => {
            try {
              const result = await postJson('/api/unmatched_folders/backfill_suggested_kind', {})
              setActionStatus(
                `Kind hints updated ${Number(result.updated) || 0} of ${Number(result.scanned) || 0} scanned.`,
              )
              setReloadKey((value) => value + 1)
            } catch (reason) {
              setError(reason)
            }
          }}
        >
          Backfill kind hints
        </Button>
        <details className="od-scan-unmatched__export">
          <summary className="od-cbtn" title="Download the current filter">
            <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" focusable="false">
              <path
                d="M12 3v12m0 0 4-4m-4 4-4-4M5 17v3h14v-3"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>{' '}
            Export
          </summary>
          <div>
            <a
              className="od-cbtn"
              href={`/api/unmatched_folders/export?${new URLSearchParams({ status, format: 'csv', ...(libraryUuid ? { library_uuid: libraryUuid } : {}), ...(platform ? { platform } : {}), ...(region ? { rom_region: region } : {}), ...(searchQuery ? { q: searchQuery } : {}), ...(why !== 'all' ? { why } : {}), ...(kind !== 'all' && kind !== 'none' ? { suggested_kind: kind } : {}) })}`}
            >
              Export CSV
            </a>
            <a
              className="od-cbtn"
              href={`/api/unmatched_folders/export?${new URLSearchParams({ status, format: 'json', ...(libraryUuid ? { library_uuid: libraryUuid } : {}), ...(platform ? { platform } : {}), ...(region ? { rom_region: region } : {}), ...(searchQuery ? { q: searchQuery } : {}), ...(why !== 'all' ? { why } : {}), ...(kind !== 'all' && kind !== 'none' ? { suggested_kind: kind } : {}) })}`}
            >
              Export JSON
            </a>
          </div>
        </details>
      </AdminPageActions>
      {linkSuccess ? (
        <PageStatus announcement="status" className="od-scan-unmatched__success">
          {linkSuccess}
        </PageStatus>
      ) : null}
      {actionStatus ? <PageStatus announcement="status">{actionStatus}</PageStatus> : null}
      <PageStatus
        loading={loading}
        loadingMessage="Loading unmatched folders…"
        error={error}
        errorMessage="Unable to load unmatched folders."
      />
      <section className="od-scan-unmatched" aria-label="Unmatched folder filters and results">
        <ScanUnmatchedFilters {...model} />
        {selectedIds.size ? (
          <div
            className="od-scan-unmatched__batch"
            role="group"
            aria-label="Selected folder actions"
          >
            <span>{selectedIds.size} selected</span>
            <Button type="button" disabled={loading} onClick={() => void runBatchAction('clear')}>
              Clear selected
            </Button>
            <Button
              type="button"
              disabled={loading}
              onClick={() => void runBatchAction('ignore_selected')}
            >
              Ignore selected
            </Button>
            <Button
              type="button"
              disabled={loading}
              onClick={() => void runBatchAction('mark_kind', 'experience')}
            >
              Mark Soft
            </Button>
            <Button
              type="button"
              disabled={loading}
              onClick={() => void runBatchAction('mark_kind', 'emulator')}
            >
              Mark Emulator
            </Button>
            <Button
              type="button"
              disabled={loading}
              onClick={() => void runBatchAction('mark_kind', 'tool')}
            >
              Mark Utility
            </Button>
            <Button type="button" disabled={loading} onClick={() => void runBatchAction('merge')}>
              Merge duplicates
            </Button>
            <Button type="button" disabled={loading} onClick={() => void runBatchAction('keep')}>
              Keep duplicates
            </Button>
            <Button type="button" disabled={loading} onClick={() => void runBatchAction('ignore')}>
              Ignore duplicates
            </Button>
            <Button
              type="button"
              onClick={() => {
                setSelectedIds(new Set())
                selectedRows.current.clear()
              }}
            >
              Deselect
            </Button>
          </div>
        ) : null}
        <ScanUnmatchedTable {...model} />
      </section>
      <OpenPathModal
        open={Boolean(pathModal)}
        path={pathModal}
        label="Unmatched folder"
        onClose={() => setPathModal('')}
      />
    </Page>
  )
}
