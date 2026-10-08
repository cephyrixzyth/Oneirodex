import { useLayoutEffect } from 'react'

export const ADMIN_TOPBAR_SLOT_ID = 'od-admin-topbar-slot'
export const ADMIN_TOPBAR_TRAIL_ID = 'od-admin-topbar-trail'
export const LEGACY_CONTENT_ID = 'admin-legacy-content'

/**
 * Lift Jinja `chrome.contextbar` into the thin admin top bar.
 *
 * Member `ContextBar` splits views into the centred page slot and the count
 * into the trail beside account. Admin previously stuffed the whole
 * `.od-contextbar` into `#od-admin-topbar-slot`, so the tab strip sat off-centre
 * (sharing the slot with the summary). Libraries now keep the count on the
 * page (Games popover); other Jinja pages may still emit a trail summary.
 *
 * Full page loads own Jinja bodies; a placeholder keeps the original home for
 * cleanup when React unmounts (SPA route).
 */
export function useLegacyContextbarPortal(enabled: boolean) {
  useLayoutEffect(() => {
    if (!enabled || typeof document === 'undefined') return undefined

    const pageSlot = document.getElementById(ADMIN_TOPBAR_SLOT_ID)
    const trailSlot = document.getElementById(ADMIN_TOPBAR_TRAIL_ID)
    const legacy = document.getElementById(LEGACY_CONTENT_ID)
    if (!pageSlot || !legacy) return undefined

    const bar =
      legacy.querySelector(':scope > .od-contextbar') || legacy.querySelector('.od-contextbar')
    if (!bar) return undefined
    // Already lifted (views live in the page slot).
    if (pageSlot.contains(bar) || pageSlot.querySelector(':scope > .od-contextbar__views')) {
      return undefined
    }

    const views = bar.querySelector(':scope > .od-contextbar__views')
    const actions = bar.querySelector(':scope > .od-contextbar__actions')
    const actionSlot = actions?.getAttribute('data-od-admin-action-slot')
    const placeholder = document.createComment('od-contextbar-home')
    bar.parentNode?.insertBefore(placeholder, bar)

    if (views) pageSlot.appendChild(views)
    if (actions) {
      const target = actionSlot === 'page' ? pageSlot : trailSlot || pageSlot
      target.appendChild(actions)
    }
    bar.remove()

    return () => {
      const restore = document.createElement('div')
      restore.className = 'od-contextbar'
      if (views) restore.appendChild(views)
      if (actions) restore.appendChild(actions)
      if (placeholder.parentNode) {
        placeholder.parentNode.insertBefore(restore, placeholder)
        placeholder.remove()
      }
    }
  }, [enabled])
}
