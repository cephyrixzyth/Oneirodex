import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useShellConfig } from '@oneirodex/ui'
import type { StoreConnectionsResponse } from '../api/ownership'
import { ContextBar } from '../chrome/ContextBar'
import { usesNewChrome } from '../chrome/usesNewChrome'
import { OwnershipReview } from '../components/stores/OwnershipReview'
import { StoreConnections } from '../components/stores/StoreConnections'
import './OwnershipPage.css'

const VIEWS = [
  { id: 'stores', label: 'Stores' },
  { id: 'review', label: 'Review matches' },
]

function totals(status: StoreConnectionsResponse | null) {
  if (!status) return null
  return status.connections.reduce(
    (sum, c) => ({
      owned: sum.owned + c.records.owned,
      matched: sum.matched + c.records.matched,
      review: sum.review + c.records.needs_review,
    }),
    { owned: 0, matched: 0, review: 0 },
  )
}

/**
 * Settings for store ownership (LIB-02). The store list is the same component
 * first-run (`/welcome`) uses, reading the same status contract; this page
 * adds the match review. Register-only: nothing is downloaded or installed.
 */
export function OwnershipPage() {
  const shellConfig = useShellConfig()
  const useNewChrome = usesNewChrome(shellConfig)
  const [searchParams, setSearchParams] = useSearchParams()
  const view = searchParams.get('view') === 'review' ? 'review' : 'stores'
  const [status, setStatus] = useState<StoreConnectionsResponse | null>(null)
  const sums = totals(status)
  const summary = sums
    ? `${sums.owned} owned · ${sums.matched} matched${sums.review ? ` · ${sums.review} to review` : ''}`
    : null

  const selectView = (id: string) => {
    const next = new URLSearchParams(searchParams)
    if (id === 'review') next.set('view', 'review')
    else next.delete('view')
    setSearchParams(next, { replace: true })
  }

  return (
    <>
      {useNewChrome ? (
        <ContextBar views={VIEWS} activeView={view} onSelectView={selectView} summary={summary} />
      ) : null}
      <div className="od-more-page od-ownership">
        {useNewChrome ? null : (
          <>
            <div className="od-page-header">
              <h1>Store Ownership</h1>
            </div>
            <div className="od-cbtn-group" role="group" aria-label="Ownership views">
              {VIEWS.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  className={`od-cbtn${view === v.id ? ' is-on' : ''}`}
                  aria-pressed={view === v.id}
                  onClick={() => selectView(v.id)}
                >
                  {v.label}
                </button>
              ))}
            </div>
          </>
        )}
        <p className="od-more-page__lede">
          Link store accounts or import lists so the library can show what you own elsewhere.
          Register-only: Oneirodex never downloads games or DRM from stores.{' '}
          <Link to="/welcome">First-time setup</Link>
        </p>
        {view === 'review' ? (
          <OwnershipReview />
        ) : (
          <StoreConnections variant="settings" onStatus={setStatus} />
        )}
      </div>
    </>
  )
}
