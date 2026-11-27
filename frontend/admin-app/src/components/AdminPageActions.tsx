import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export const ADMIN_TOPBAR_PAGE_SLOT_ID = 'od-admin-topbar-slot'
export const ADMIN_TOPBAR_TRAIL_SLOT_ID = 'od-admin-topbar-trail'
export const ADMIN_TOPBAR_TITLE_SLOT_ID = 'od-admin-topbar-title'

/**
 * Page actions in the admin top bar (W33-9).
 *
 * Identity already lives in the rail. Buttons that used to sit in
 * `.od-admin-actions-row` on the page belong in the thin top bar — same leftover
 * UIR-3/UIR-7 named on the member side.
 *
 * `slot="page"` (default) portals into `#od-admin-topbar-slot` (centre).
 * `slot="trail"` portals into `#od-admin-topbar-trail` (right, beside account).
 * `slot="title"` portals into `#od-admin-topbar-title` (left, after rail toggle).
 * Falls back to the inline row in tests and any host without the bar.
 */
export function AdminPageActions({
  children,
  label = 'Page actions',
  slot = 'page',
}: {
  children?: ReactNode
  label?: string
  slot?: 'page' | 'trail' | 'title'
}) {
  const [host, setHost] = useState<HTMLElement | null>(null)
  const slotId =
    slot === 'trail'
      ? ADMIN_TOPBAR_TRAIL_SLOT_ID
      : slot === 'title'
        ? ADMIN_TOPBAR_TITLE_SLOT_ID
        : ADMIN_TOPBAR_PAGE_SLOT_ID

  useEffect(() => {
    setHost(document.getElementById(slotId))
  }, [slotId])

  const cluster =
    slot === 'title' ? (
      <div className="od-topbar__title-block" role="group" aria-label={label}>
        {children}
      </div>
    ) : (
      <div className="od-cbtn-group" role="group" aria-label={label}>
        {children}
      </div>
    )

  if (host) {
    return createPortal(cluster, host)
  }

  // A title with no bar to sit in is not repeated inline: the page's own
  // (visually hidden) h1 already names it.
  if (slot === 'title') return null

  return <div className="od-admin-actions-row">{children}</div>
}
