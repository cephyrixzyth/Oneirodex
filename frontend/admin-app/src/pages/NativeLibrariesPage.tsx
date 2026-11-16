import { Button } from '@oneirodex/ui'
import { LibrariesPanel } from '../components/LibrariesPanel'
import { LibraryProposalsPanel } from '../components/LibraryProposalsPanel'
import { LibraryDoctorPanel } from '../components/LibraryDoctorPanel'
import { RenameGamePanel } from '../components/RenameGamePanel'
import { LibraryFreshnessPanel } from '../components/LibraryFreshnessPanel'
import { Page } from '../components/Page'
import { ScanConflictModal } from '../components/ScanConflictModal'
import { useLibraryRefreshAll } from '../hooks/useLibraryRefreshAll'
import { CreateLibraryForm } from '../components/CreateLibraryForm'

import { useNavigate } from 'react-router-dom'
import { AdminLink } from '../components/AdminLink'

export function NativeLibraryAddPage() {
  const navigate = useNavigate()
  return (
    <Page title="Create library">
      <div className="od-admin-panel__toolbar">
        <AdminLink className="od-cbtn" to="/libraries">
          Back to libraries
        </AdminLink>
      </div>
      <CreateLibraryForm onComplete={() => navigate('/libraries')} />
    </Page>
  )
}

export function NativeLibrariesPage() {
  const { conflictOpen, refreshing, startRefreshAll, onConflictChoose, onConflictClose } =
    useLibraryRefreshAll()

  return (
    <Page title="Libraries" lede="Create, organize, scan and maintain game libraries.">
      <LibrariesPanel
        managementActions={
          <>
            <AdminLink className="od-cbtn" to="/admin/scan-controls">
              Start or schedule a scan
            </AdminLink>
            <Button
              type="button"
              className="od-btn--accent"
              onClick={() => void startRefreshAll()}
              disabled={refreshing}
            >
              {refreshing ? 'Refreshing…' : 'Refresh all libraries'}
            </Button>
            <AdminLink className="od-cbtn" to="/scan_management?active_tab=jobs">
              Scan jobs
            </AdminLink>
          </>
        }
      />
      <LibraryDoctorPanel />
      <RenameGamePanel />
      <LibraryFreshnessPanel />
      <LibraryProposalsPanel />
      <ScanConflictModal
        open={conflictOpen}
        busy={refreshing}
        onChoose={onConflictChoose}
        onClose={onConflictClose}
      />
    </Page>
  )
}
