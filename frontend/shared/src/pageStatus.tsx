import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { loadingEllipsisFrame, loadingMessageBase } from './loadingStatusText.js'
import { Button } from '@oneirodex/ui'

/**
 * Shared loading / error / empty status for SPA pages — `@oneirodex/ui`.
 *
 * Three copies of this had drifted across the SPAs (member `src/components/`,
 * admin `src/`, ops `src/`). The error-shape readers `resolveErrorMessage` /
 * `resolveErrorDetail` were byte-identical in all three; the component itself
 * diverged only in the loading branch:
 *
 *   - admin / ops: a plain animated "Loading …" line.
 *   - member: a rotating `LoadingMotif` (console-hardware glyphs), which is
 *     member-side polish loaded by the member bundle — admin deliberately did
 *     not pull that dependency in, and ops cannot (its Docker build has no
 *     Flask theme tree).
 *
 * So the canonical component here is the plain-line flavour, and it takes an
 * optional `renderLoading` render prop. member-app passes its motif renderer;
 * admin and ops pass nothing and get the plain line. One implementation, the
 * deliberate per-app difference expressed as a prop rather than a fork.
 *
 * The `.od-page-status` CSS lives in the shared theme
 * (`oneirodex/setup/default_theme/css/od-primitives.css`), loaded by base.html
 * and base_admin.html, and on the Jinja Ops shell — so member, admin and the
 * server-rendered pages all render this from one source. This module imports no
 * CSS of its own.
 *
 * Precedence is error → loading → empty → children. Error outranks loading so a
 * failed refresh of already-rendered data does not sit spinning forever.
 *
 * Error uses role="alert" (assertive) because it is an interruption the user
 * must act on; loading and empty stay role="status" (polite).
 */

/** The loose error shapes still in the tree, alongside a thrown `Error`. */
interface ErrorBag {
  error?: unknown
  message?: unknown
  status?: unknown
  error_code?: unknown
}

/** Args handed to a caller-supplied `renderLoading` render prop. */
export interface RenderLoadingArgs {
  inline: boolean
  className: string
  loadingMessage: string
}

/**
 * Read the human sentence out of a failed request (GT-A2).
 *
 * Backend is mid-migration onto the GT-B1 envelope, so this deliberately
 * accepts every legacy shape that still exists in the tree:
 *   { error: 'text' }        — dominant legacy shape
 *   { message: 'text' }      — second legacy shape
 *   { error: { message } }   — defensive; some upstream proxies nest
 *   an Error instance        — thrown by fetch wrappers on network failure
 *
 * Never surfaces a raw status code as the headline; that goes in `detail`.
 */
export function resolveErrorMessage(error: unknown, fallback = 'Something went wrong.'): string {
  if (!error) return fallback
  if (typeof error === 'string') return error.trim() || fallback

  if (error instanceof Error) {
    return error.message?.trim() || fallback
  }

  const bag = error as ErrorBag
  const direct = bag.error
  if (typeof direct === 'string' && direct.trim()) return direct.trim()
  if (direct && typeof direct === 'object') {
    const nested = (direct as { message?: unknown }).message
    if (typeof nested === 'string' && nested.trim()) return nested.trim()
  }

  if (typeof bag.message === 'string' && bag.message.trim()) {
    return bag.message.trim()
  }

  return fallback
}

/** Operator-facing detail line — status code / stable error code, never the headline. */
export function resolveErrorDetail(error: unknown): string | null {
  // Errors are included on purpose: the fetch wrappers throw Error objects that
  // carry `status` / `error_code` off the GT-B1 envelope, and bailing on
  // `instanceof Error` dropped exactly the fields this line exists to show. A
  // plain Error from a network failure has neither, so it still yields null.
  if (!error || typeof error !== 'object') return null
  const bag = error as ErrorBag
  const parts: string[] = []
  if (bag.status != null) parts.push(`HTTP ${bag.status}`)
  if (typeof bag.error_code === 'string' && bag.error_code) parts.push(bag.error_code)
  return parts.length ? parts.join(' · ') : null
}

function DefaultLoadingStatus({ inline, className, loadingMessage }: RenderLoadingArgs) {
  const base = loadingMessageBase(loadingMessage)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
    if (reduce) return undefined
    const timer = window.setInterval(() => setTick((n) => n + 1), 420)
    return () => window.clearInterval(timer)
  }, [])

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
      <p className="od-page-status__message">
        <span className="od-page-status__message-base">{base}</span>
        <span className="od-page-status__ellipsis" aria-hidden="true">
          {loadingEllipsisFrame(tick)}
        </span>
      </p>
    </div>
  )
}

export interface PageStatusProps {
  loading?: boolean
  error?: unknown
  onRetry?: (() => void) | null
  errorMessage?: string | null
  retryLabel?: string
  emptyMessage?: string | null
  loadingMessage?: string
  children?: ReactNode
  className?: string
  inline?: boolean
  renderLoading?: ((args: RenderLoadingArgs) => ReactNode) | null
}

export function PageStatus({
  loading = false,
  error = null,
  onRetry = null,
  errorMessage = null,
  retryLabel = 'Try again',
  emptyMessage = null,
  loadingMessage = 'Loading…',
  children = null,
  className = '',
  inline = false,
  renderLoading = null,
}: PageStatusProps): ReactNode {
  if (error) {
    const message = errorMessage || resolveErrorMessage(error)
    const detail = resolveErrorDetail(error)
    return (
      <div
        className={`od-page-status od-page-status--error${className ? ` ${className}` : ''}`}
        role="alert"
      >
        <div className="od-page-status__body">
          <p className="od-page-status__message">{message}</p>
          {detail ? <p className="od-page-status__detail">{detail}</p> : null}
        </div>
        {onRetry ? (
          <Button type="button" size="sm" onClick={onRetry}>
            {retryLabel}
          </Button>
        ) : null}
      </div>
    )
  }

  if (loading) {
    const node =
      typeof renderLoading === 'function' ? (
        renderLoading({ inline, className, loadingMessage })
      ) : (
        <DefaultLoadingStatus
          inline={inline}
          className={className}
          loadingMessage={loadingMessage}
        />
      )
    if (inline || typeof document === 'undefined') return node
    return createPortal(node, document.body)
  }

  if (emptyMessage) {
    return (
      <div
        className={`od-page-status od-page-status--empty${className ? ` ${className}` : ''}`}
        role="status"
      >
        <p className="od-page-status__message">{emptyMessage}</p>
        {children}
      </div>
    )
  }

  return children
}

export default PageStatus
