import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { StoreConnectionsResponse } from '../api/ownership'
import { StoreConnections } from '../components/stores/StoreConnections'
import { dismissStoreSetup } from '../components/stores/StoreSetupPrompt'
import { useViewer } from '@oneirodex/ui'
import './WelcomePage.css'

/**
 * First-run store setup (LIB-02). Three short steps toward a useful library:
 * link or import stores (the same list Settings shows), glance at matches that
 * need a decision, then open the library filtered to what you own. Every step
 * can be skipped; running it again never duplicates titles.
 */
export function WelcomePage() {
  const viewer = useViewer()
  const [status, setStatus] = useState<StoreConnectionsResponse | null>(null)
  const counts = (status?.connections || []).reduce(
    (sum, c) => ({
      owned: sum.owned + c.records.owned,
      matched: sum.matched + c.records.matched,
      review: sum.review + c.records.needs_review,
    }),
    { owned: 0, matched: 0, review: 0 },
  )
  const libraryHref = counts.matched > 0 ? '/library?ownership=owned' : '/library'

  return (
    <div className="od-more-page od-welcome">
      <div className="od-page-header">
        <h1>Set up your stores</h1>
      </div>
      <p className="od-more-page__lede">
        Tell Oneirodex which games you already own elsewhere, so the library can mark them. This
        only records ownership: nothing is downloaded, installed or bought.
      </p>

      <ol className="od-welcome__steps">
        <li className="od-welcome__step">
          <h2>1. Link or import</h2>
          <StoreConnections variant="first-run" onStatus={setStatus} />
        </li>
        <li className="od-welcome__step">
          <h2>2. Check the matches</h2>
          <p className="od-welcome__text">
            {counts.owned === 0
              ? 'Once a store is linked or a list imported, titles show up here.'
              : counts.review > 0
                ? `${counts.owned} titles recorded, ${counts.matched} matched to your library. ${counts.review} are not matched to a library game yet: check them before anything is linked.`
                : `${counts.owned} titles recorded, ${counts.matched} matched to your library.`}
          </p>
          {counts.review > 0 ? (
            <Link className="od-btn od-btn--sm" to="/ownership?view=review">
              Review {counts.review} titles
            </Link>
          ) : null}
        </li>
        <li className="od-welcome__step">
          <h2>3. Open your library</h2>
          <p className="od-welcome__text">
            {counts.matched > 0
              ? 'Open the library showing the games you own. Clear the filter to see everything.'
              : 'You can come back to this any time from Ownership.'}
          </p>
          <Link
            className="od-btn od-btn--primary"
            to={libraryHref}
            onClick={() => dismissStoreSetup(viewer.userId)}
          >
            {counts.matched > 0 ? 'Show games I own' : 'Go to the library'}
          </Link>
        </li>
      </ol>
    </div>
  )
}
