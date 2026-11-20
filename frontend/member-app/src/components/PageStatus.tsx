import { PageStatus as BasePageStatus, loadingMessageBase } from '@oneirodex/ui'

import './PageStatus.css'
import { LoadingMotif } from './LoadingMotif'
import { useLoadingMotifId } from './loadingMotifApi'

/**
 * Member-app `PageStatus` — the shared `@oneirodex/ui` component with the
 * member-only motif loading state plugged in.
 *
 * The loading / error / empty behaviour, the error-shape readers and the
 * `.od-page-status` classes all live in `@oneirodex/ui` now (wave B1.2), shared
 * with the admin and ops SPAs. What stays here is the one deliberate member
 * difference: a preference-aware `LoadingMotif` (console-hardware glyphs) instead of the
 * plain "Loading …" line. That polish is loaded by the member bundle; admin
 * chose not to pull the dependency in and ops cannot. The shared component
 * takes a `renderLoading` render prop for exactly this.
 *
 * `resolveErrorMessage` / `resolveErrorDetail` are re-exported so the member
 * call sites that import them from here keep working unchanged.
 */
export { resolveErrorMessage, resolveErrorDetail } from '@oneirodex/ui'

function LoadingStatus({ inline, className, seedMotif, loadingMessage }: LooseProps) {
  const base = loadingMessageBase(loadingMessage)

  return (
    <div
      className={`od-page-status od-page-status--loading${
        inline ? '' : ' od-page-status--takeover'
      }${className ? ` ${className}` : ''}`}
      role="status"
      aria-busy="true"
      aria-live="polite"
    >
      <LoadingMotif motifId={seedMotif} size={inline ? 'md' : 'lg'} title={base} />
      <p className="od-page-status__message">
        <span className="od-page-status__message-base">{base}</span>
        <span className="od-page-status__ellipsis" aria-hidden="true">
          {' ...'}
        </span>
      </p>
    </div>
  )
}

/**
 * Same props as the shared `PageStatus`, plus `motifId` — the member's persisted
 * loading-motif preference, resolved through `useLoadingMotifId` and used for
 * the whole request.
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
