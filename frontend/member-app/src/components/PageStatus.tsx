import { useEffect, useState } from 'react'

import {
  PageStatus as BasePageStatus,
  loadingEllipsisFrame,
  loadingMessageBase,
} from '@oneirodex/ui'

import './PageStatus.css'
import { LoadingMotif, LOADING_MOTIF_IDS, normalizeLoadingMotifId } from './LoadingMotif'
import { useLoadingMotifId } from './loadingMotifApi'

/**
 * Member-app `PageStatus` — the shared `@oneirodex/ui` component with the
 * member-only motif loading state plugged in.
 *
 * The loading / error / empty behaviour, the error-shape readers and the
 * `.od-page-status` classes all live in `@oneirodex/ui` now (wave B1.2), shared
 * with the admin and ops SPAs. What stays here is the one deliberate member
 * difference: a rotating `LoadingMotif` (console-hardware glyphs) instead of the
 * plain "Loading …" line. That polish is loaded by the member bundle; admin
 * chose not to pull the dependency in and ops cannot. The shared component
 * takes a `renderLoading` render prop for exactly this.
 *
 * `resolveErrorMessage` / `resolveErrorDetail` are re-exported so the member
 * call sites that import them from here keep working unchanged.
 */
export { resolveErrorMessage, resolveErrorDetail } from '@oneirodex/ui'

// Faster animation for visibility during brief loads (user sees motion even in 1-2s loads)
const MOTIF_ROTATE_MS = 400
const ELLIPSIS_MS = 150

function LoadingStatus({ inline, className, seedMotif, loadingMessage }: LooseProps) {
  const base = loadingMessageBase(loadingMessage)
  const [tick, setTick] = useState(0)
  const [motifIndex, setMotifIndex] = useState(0)

  const pool = LOADING_MOTIF_IDS
  const startId = normalizeLoadingMotifId(seedMotif) || pool[0]
  const startIndex = Math.max(0, pool.indexOf(startId))

  useEffect(() => {
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
    if (reduce) return undefined

    const ellipsisTimer = window.setInterval(() => {
      setTick((n) => n + 1)
    }, ELLIPSIS_MS)
    const motifTimer = window.setInterval(() => {
      setMotifIndex((n) => n + 1)
    }, MOTIF_ROTATE_MS)
    return () => {
      window.clearInterval(ellipsisTimer)
      window.clearInterval(motifTimer)
    }
  }, [])

  const motifId = pool[(startIndex + motifIndex) % pool.length]
  const label = `${base}${loadingEllipsisFrame(tick)}`

  return (
    <div
      className={`od-page-status od-page-status--loading${
        inline ? '' : ' od-page-status--takeover'
      }${className ? ` ${className}` : ''}`}
      role="status"
      aria-busy="true"
      aria-live="polite"
    >
      <span className="od-page-status__spinner" aria-hidden="true" />
      <LoadingMotif motifId={motifId} size={inline ? 'md' : 'lg'} title={label} />
      <p className="od-page-status__message">
        <span className="od-page-status__message-base">{base}</span>
        <span className="od-page-status__ellipsis" aria-hidden="true">
          {loadingEllipsisFrame(tick)}
        </span>
      </p>
    </div>
  )
}

/**
 * Same props as the shared `PageStatus`, plus `motifId` — the member's persisted
 * loading-motif preference, resolved through `useLoadingMotifId` and seeded into
 * the rotation.
 */
export function PageStatus({ motifId = null, ...props }: LooseProps) {
  const resolvedMotif = useLoadingMotifId(motifId)
  return (
    <BasePageStatus
      {...props}
      renderLoading={({ inline, className, loadingMessage }) => (
        <LoadingStatus
          inline={inline}
          className={className}
          seedMotif={resolvedMotif}
          loadingMessage={loadingMessage}
        />
      )}
    />
  )
}

export default PageStatus
