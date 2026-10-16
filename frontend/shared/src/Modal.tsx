import { useEffect, useRef, type MouseEvent, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'

/**
 * `<Modal>` — the dialog shell every popup was hand-rolling.
 *
 * OpenPathModal (twice), OpsLogModal, ScanConflictModal, the lightbox and the
 * account modal each re-implemented the same five things: a portal to
 * `document.body`, Escape closes, clicking the backdrop closes while clicking
 * the panel does not, `role="dialog" aria-modal`, and moving focus in on open.
 * Some did four of the five. This owns them once; the dialog keeps its own
 * CSS — `className` is the overlay, `panelClassName` the panel — so adopting
 * it changes no pixels.
 *
 * Why a portal: a host page's stacking rules can reach a modal rendered in
 * place (`.od-details-page > :not(…) { position: relative }` once pinned a
 * `position: fixed` lightbox into the page flow — the memory note on
 * verifying UI fixes live exists because of it). Rendered under `body`, no
 * ancestor rule applies.
 *
 * Focus: on open, `initialFocusRef` if given, else the first focusable inside
 * the panel, else the panel itself (which carries `tabIndex={-1}` for that).
 * Tab and Shift+Tab cycle inside the panel. On close, focus goes back to
 * whatever had it before the modal opened — the control that opened it, in
 * practice — so a keyboard user does not land at the top of the page.
 */

export interface ModalProps {
  open: boolean
  onClose?: () => void
  /** id of the element that titles the dialog (preferred over `label`). */
  labelledBy?: string
  /** Plain-text title when nothing visible titles the dialog. */
  label?: string
  /** Overlay classes — the dialog's own `.od-thing` root. */
  className?: string
  /** Panel classes — the dialog's own `.od-thing__panel`. */
  panelClassName?: string
  /** Optional state hook for panel styling, emitted as `data-panel`. */
  panelData?: string
  /** Element to restore focus to when its launcher is removed while opening. */
  restoreFocusRef?: RefObject<HTMLElement | null>
  /** Element to focus on open; defaults to the first focusable in the panel. */
  initialFocusRef?: RefObject<HTMLElement | null>
  /** Escape closes unless the dialog is mid-action. Default true. */
  closeOnEscape?: boolean
  /** Backdrop click closes. Default true. */
  closeOnBackdrop?: boolean
  /** Hold `body` scroll while open (tall dialogs over long pages). Default false. */
  lockScroll?: boolean
  children: ReactNode
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (el) => !el.hasAttribute('hidden') && el.getAttribute('aria-hidden') !== 'true',
  )
}

export function Modal({
  open,
  onClose,
  labelledBy,
  label,
  className = '',
  panelClassName = '',
  panelData,
  restoreFocusRef,
  initialFocusRef,
  closeOnEscape = true,
  closeOnBackdrop = true,
  lockScroll = false,
  children,
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement | null>(null)
  const restoreRef = useRef<HTMLElement | null>(null)
  const closeRef = useRef({ onClose, closeOnEscape })
  closeRef.current = { onClose, closeOnEscape }

  useEffect(() => {
    if (!open) return undefined
    restoreRef.current =
      restoreFocusRef?.current ?? (document.activeElement as HTMLElement | null) ?? null
    const panel = panelRef.current
    const target = initialFocusRef?.current ?? (panel ? (focusables(panel)[0] ?? panel) : null)
    target?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (closeRef.current.closeOnEscape) {
          event.stopPropagation()
          closeRef.current.onClose?.()
        }
        return
      }
      if (event.key !== 'Tab' || !panel) return
      const items = focusables(panel)
      if (!items.length) {
        event.preventDefault()
        panel.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !panel.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    const previousOverflow = document.body.style.overflow
    if (lockScroll) document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      if (lockScroll) document.body.style.overflow = previousOverflow
      const back = restoreRef.current
      if (back && back.isConnected && typeof back.focus === 'function') back.focus()
    }
  }, [open, lockScroll, initialFocusRef, restoreFocusRef])

  if (!open || typeof document === 'undefined') return null

  const onBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (!closeOnBackdrop) return
    if (event.target === event.currentTarget) onClose?.()
  }

  return createPortal(
    <div
      className={className}
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      aria-label={labelledBy ? undefined : label}
      onClick={onBackdrop}
    >
      <div data-panel={panelData} ref={panelRef} className={panelClassName} tabIndex={-1}>
        {children}
      </div>
    </div>,
    document.body,
  )
}

export default Modal
