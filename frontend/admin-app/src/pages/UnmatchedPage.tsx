import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { PageStatus } from '@oneirodex/ui'
import { DupeGlance } from '../components/DupeGlance'
import { OpenPathModal } from '../components/OpenPathModal'
import { Page } from '../components/Page'
import './UnmatchedPage.css'

interface PathModalState {
  path?: string
  label?: string
  matchReason?: string
}

export function UnmatchedPage() {
  const [pathModal, setPathModal] = useState<PathModalState | null>(null)
  const location = useLocation()
  const navigate = useNavigate()
  const state = location.state as { linkSuccess?: unknown } | null
  const [linkSuccess, setLinkSuccess] = useState(() =>
    typeof state?.linkSuccess === 'string' ? state.linkSuccess : '',
  )

  useEffect(() => {
    if (typeof state?.linkSuccess !== 'string') return
    setLinkSuccess(state.linkSuccess)
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
  }, [location.pathname, location.search, navigate, state?.linkSuccess])

  return (
    <Page
      title="Unmatched folders"
      lede="Review unmatched and duplicate folders, compare candidates, and apply a correction."
    >
      <div className="od-admin-actions-row">
        <a href="/admin/scan-jobs">Return to scan jobs</a>
      </div>
      {linkSuccess ? (
        <PageStatus announcement="status" className="od-unmatched__success">
          {linkSuccess}
        </PageStatus>
      ) : null}
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
