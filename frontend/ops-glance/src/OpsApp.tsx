import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchOpsSummary, type OpsSummary } from './api/summary'
import { PageStatus } from '@oneirodex/ui'
import { DeepLinks } from './components/DeepLinks'
import { HostPanel } from './components/HostPanel'
import { IssuesList } from './components/IssuesList'
import { LibraryPulse } from './components/LibraryPulse'
import { NetworkPanel } from './components/NetworkPanel'
import { RecentErrors } from './components/RecentErrors'
import { ScansPanel } from './components/ScansPanel'
import { StatusBanner } from './components/StatusBanner'

function isAbortError(error: unknown): boolean {
  return (error as { name?: string } | null | undefined)?.name === 'AbortError'
}

interface RequestRef {
  id: number
  controller: AbortController | null
}

export interface OpsAppProps {
  pollMs?: number
}

export function OpsApp({ pollMs = 15000 }: OpsAppProps) {
  const [snapshot, setSnapshot] = useState<OpsSummary | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const requestRef = useRef<RequestRef>({ id: 0, controller: null })

  const refresh = useCallback(() => {
    requestRef.current.controller?.abort()
    const controller = new AbortController()
    const id = requestRef.current.id + 1
    requestRef.current = { id, controller }
    setLoading(true)
    setError(null)

    fetchOpsSummary({ signal: controller.signal })
      .then((nextSnapshot) => {
        if (requestRef.current.id === id && !controller.signal.aborted) {
          setSnapshot(nextSnapshot)
          setError(null)
          setLoading(false)
        }
      })
      .catch((requestError) => {
        if (
          requestRef.current.id === id &&
          !controller.signal.aborted &&
          !isAbortError(requestError)
        ) {
          setError(requestError)
          setLoading(false)
        }
      })
  }, [])

  useEffect(() => {
    refresh()
    const intervalId = window.setInterval(refresh, pollMs)

    return () => {
      window.clearInterval(intervalId)
      requestRef.current.controller?.abort()
    }
  }, [pollMs, refresh])

  return (
    <main className="ops-glance">
      <header className="ops-glance__header">
        <h1 className="ops-glance__title">Operations glance</h1>
        <button type="button" onClick={refresh} disabled={loading}>
          Refresh
        </button>
      </header>

      {error && snapshot ? <PageStatus error={error} onRetry={refresh} retryLabel="Retry" /> : null}

      {!snapshot ? (
        <PageStatus
          loading={loading}
          error={error}
          onRetry={refresh}
          retryLabel="Retry"
          loadingMessage="Loading operations summary…"
          // Ops renders its loading line in-flow (no portal / full-page
          // takeover) — the shared default; `inline` keeps that behaviour.
          inline
        />
      ) : (
        <>
          <StatusBanner issues={snapshot.issues} asOf={snapshot.as_of} />
          <div className="ops-glance__grid">
            <HostPanel host={snapshot.host} />
            <NetworkPanel network={snapshot.network} />
            <IssuesList issues={snapshot.issues} />
            <ScansPanel scans={snapshot.scans} />
            <LibraryPulse library={snapshot.library} />
            <RecentErrors errors={snapshot.recent_errors} />
          </div>
        </>
      )}

      <DeepLinks />
    </main>
  )
}
