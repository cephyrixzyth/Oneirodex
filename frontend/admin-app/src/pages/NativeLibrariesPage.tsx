import { Button } from '@oneirodex/ui'
import { LibrariesPanel } from '../components/LibrariesPanel'
import { LibraryProposalsPanel } from '../components/LibraryProposalsPanel'
import { LibraryDoctorPanel } from '../components/LibraryDoctorPanel'
import { RenameGamePanel } from '../components/RenameGamePanel'
import { LibraryFreshnessPanel } from '../components/LibraryFreshnessPanel'
import { Page } from '../components/Page'
import { ScanConflictModal } from '../components/ScanConflictModal'
import { useLibraryRefreshAll } from '../hooks/useLibraryRefreshAll'

export function NativeLibrariesPage() {
  const { conflictOpen, refreshing, startRefreshAll, onConflictChoose, onConflictClose } =
    useLibraryRefreshAll()

  return (
    <Page title="Libraries" lede="Create, organize, scan and maintain game libraries.">
      <div className="od-admin-panel__toolbar">
        <a className="od-cbtn" href="/admin/scan-controls">
          Start or schedule a scan
        </a>
        <Button
          type="button"
          className="od-btn--accent"
          onClick={() => void startRefreshAll()}
          disabled={refreshing}
        >
          {refreshing ? 'Refreshing…' : 'Refresh all libraries'}
        </Button>
        <a className="od-cbtn" href="/admin/scan-jobs">
          Scan jobs
        </a>
      </div>
      <LibraryDoctorPanel />
      <RenameGamePanel />
      <LibraryFreshnessPanel />
      <LibraryProposalsPanel />
      <LibrariesPanel />
      <ScanConflictModal
        open={conflictOpen}
        busy={refreshing}
        onChoose={onConflictChoose}
        onClose={onConflictClose}
      />
    </Page>
  )
}
