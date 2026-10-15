import { useState } from 'react'
import { DupeGlance } from '../components/DupeGlance'
import { OpenPathModal } from '../components/OpenPathModal'
import { Page } from '../components/Page'

interface PathModalState {
  path?: string
  label?: string
  matchReason?: string
}

export function UnmatchedPage() {
  const [pathModal, setPathModal] = useState<PathModalState | null>(null)

  return (
    <Page
      title="Unmatched folders"
      lede="Review unmatched and duplicate folders, compare candidates, and apply a correction."
    >
      <div className="od-admin-actions-row">
        <a href="/admin/scan-jobs">Return to scan jobs</a>
      </div>
      <DupeGlance onOpenPath={setPathModal} />
      <OpenPathModal
        open={Boolean(pathModal)}
        path={pathModal?.path || ''}
        label={pathModal?.label || 'Path'}
        matchReason={pathModal?.matchReason || ''}
        onClose={() => setPathModal(null)}
      />
    </Page>
  )
}
