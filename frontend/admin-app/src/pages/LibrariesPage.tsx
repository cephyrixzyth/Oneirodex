import { useEffect, useState } from 'react'
import { PageStatus, Button } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
import { DataTable } from '../components/DataTable'
import { ImportLeafLibraries } from '../components/ImportLeafLibraries'
import { Page } from '../components/Page'
import { CreateLibraryForm } from '../components/CreateLibraryForm'
import { ProposeLeafLibraries } from '../components/ProposeLeafLibraries'
import { ScanConflictModal } from '../components/ScanConflictModal'
import { useLibraryRefreshAll } from '../hooks/useLibraryRefreshAll'
import { useLibraryScan } from '../hooks/useLibraryScan'

export function LibrariesPage() {
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const { conflictOpen, refreshing, startRefreshAll, onConflictChoose, onConflictClose } =
    useLibraryRefreshAll()
  const {
    conflictOpen: scanConflictOpen,
    busyKey: scanBusyKey,
    startScan,
    onConflictChoose: onScanConflictChoose,
    onConflictClose: onScanConflictClose,
  } = useLibraryScan()

  useEffect(() => {
    getJson('/api/get_libraries')
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch(setError)
  }, [reloadKey])

  return (
    <Page
      title="Libraries & scans"
      lede="Manage library folders and platforms. Sibling scan pages live under Libraries & scans in the rail."
    >
      <PageStatus error={error} errorMessage="Unable to load libraries." />
      <p className="od-admin-lede">
        Prefer the unified classic page:{' '}
        <a href="/scan_management?active_tab=auto">Scan jobs</a>
        {' · '}
        Library hero image:{' '}
        <a href="/admin/art_studio#stock">Choose image from Backup &amp; stock</a>
        {' · '}
        <a href="#propose-leaf">Propose leaf libraries</a>
        {' · '}
        <a href="#import-leaf">Import CSV/JSON</a>
      </p>
      <CreateLibraryForm onCreated={() => setReloadKey((key) => key + 1)} />
      <div className="od-admin-panel">
        <div className="od-admin-panel__toolbar">
          <Button
            type="button"
            className="od-btn--accent"
            onClick={() => void startRefreshAll()}
            disabled={refreshing}
          >
            {refreshing ? 'Refreshing…' : 'Refresh all libraries'}
          </Button>
          <p className="od-admin-lede od-admin-lede--tight">
            Re-scans each library’s last scan folder. When a scan is already running, choose{' '}
            <strong>Queue</strong> (default) or <strong>Force run now</strong>.
          </p>
        </div>
        {!rows && !error ? (
          <PageStatus loading loadingMessage="Loading libraries…" />
        ) : rows ? (
          // Loading and empty stay distinct: PageStatus owns "still fetching";
          // DataTable owns "no rows" so the toolbar and frame stay in place.
          <DataTable
            rows={rows}
            getRowKey={(lib) => lib.uuid}
            emptyMessage="No libraries yet. Add one to start scanning."
            initialSort={{ key: 'name', dir: 'asc' }}
            dense
            columns={[
              { key: 'name', label: 'Name' },
              {
                key: 'uuid',
                label: 'UUID',
                render: (lib) => <code>{lib.uuid}</code>,
              },
              {
                key: 'last_scan_folder',
                label: 'Last scan folder',
                value: (lib) => lib.last_scan_folder || '',
                render: (lib) => (lib.last_scan_folder ? <code>{lib.last_scan_folder}</code> : '—'),
              },
              {
                // Scanning one library is the thing this page is for, and it
                // was only reachable from the Jinja surface. Same endpoint and
                // same Queue / Force conflict handling as Refresh all.
                key: 'scan',
                label: 'Scan',
                sortable: false,
                render: (lib) => (
                  <Button
                    type="button"
                    size="sm"
                    disabled={scanBusyKey === lib.uuid || !lib.last_scan_folder}
                    title={
                      lib.last_scan_folder
                        ? `Re-scan ${lib.last_scan_folder}`
                        : 'No last scan folder — run one Auto Scan from Libraries & scans first.'
                    }
                    onClick={() =>
                      void startScan({
                        key: lib.uuid,
                        libraryUuid: lib.uuid,
                        label: lib.name,
                      })
                    }
                  >
                    {scanBusyKey === lib.uuid ? 'Starting…' : 'Scan'}
                  </Button>
                ),
              },
            ]}
          />
        ) : null}
      </div>
      <div id="propose-leaf">
        <ProposeLeafLibraries />
      </div>
      <div id="import-leaf">
        <ImportLeafLibraries />
      </div>
      <ScanConflictModal
        open={conflictOpen}
        busy={refreshing}
        onChoose={onConflictChoose}
        onClose={onConflictClose}
      />
      {/* A second instance rather than one shared modal: the two buttons post
          to different endpoints with different bodies, and the choice the
          operator makes has to go back to the request that was refused. */}
      <ScanConflictModal
        open={scanConflictOpen}
        busy={Boolean(scanBusyKey)}
        onChoose={onScanConflictChoose}
        onClose={onScanConflictClose}
      />
    </Page>
  )
}
