import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'od-rail-state'
const MOBILE_QUERY = '(max-width: 900px)'

export type RailStateValue = 'open' | 'collapsed' | 'expanded'

export interface RailState {
  collapsed: boolean
  drawerOpen: boolean
  isMobile: boolean
  /** Value for the shell's `data-rail` attribute. */
  railState: RailStateValue
  toggle: () => void
  closeDrawer: () => void
}

/**
 * Rail open/collapsed state, shared by both shells (GT-B2).
 *
 * Lives in frontend/shared rather than in either app because member-app and
 * admin-app are separate Vite builds that cannot import from one another. The
 * rail behaves identically in both, and a copy in each would be two things to
 * keep in step — exactly the pattern the GT-A4 button work was undoing.
 * Imported by relative path; there is no package boundary to set up.
 *
 * The rail has three states, not two, and they do not mean the same thing on
 * every viewport:
 *
 *   expanded   desktop default — icons plus labels
 *   collapsed  desktop, icon-only strip; labels stay in the a11y tree
 *   open       mobile only — the drawer is showing over the content
 *
 * Keeping "collapsed" and "open" as one attribute value would make the mobile
 * drawer inherit whatever the user last chose on desktop, so a member who
 * collapsed the rail on a laptop would find the phone drawer showing bare
 * icons. They are separate here, and the stylesheet re-expands labels under the
 * mobile breakpoint regardless of the persisted desktop preference.
 *
 * Only the desktop preference is persisted. A drawer that reopened itself on
 * next load because it was open when you navigated away would be a bug.
 */
export function useRailState(): RailState {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(MOBILE_QUERY).matches
  })
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false
    try {
      return window.localStorage.getItem(STORAGE_KEY) === 'collapsed'
    } catch {
      // Private mode / disabled storage must not break navigation.
      return false
    }
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const drawerOpener = useRef<HTMLElement | null>(null)

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, collapsed ? 'collapsed' : 'expanded')
    } catch {
      /* not fatal — the rail just will not remember */
    }
  }, [collapsed])

  // Close the drawer when the viewport grows past the breakpoint, or it stays
  // "open" invisibly and the next mobile resize flashes it back in.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined
    const mq = window.matchMedia(MOBILE_QUERY)
    function onChange(event: MediaQueryListEvent) {
      setIsMobile(event.matches)
      if (!event.matches) setDrawerOpen(false)
    }
    setIsMobile(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // The mobile rail is a modal drawer: put focus inside it, keep keyboard
  // focus there, and make the rest of the shell inert for keyboard and AT.
  useEffect(() => {
    if (!drawerOpen || !isMobile) return undefined
    const rail = document.querySelector<HTMLElement>('.od-rail')
    const parent = rail?.parentElement
    if (!rail || !parent) return undefined
    const railNode = rail

    const previousInert = new Map<HTMLElement, boolean>()
    Array.from(parent.children).forEach((child) => {
      if (!(child instanceof HTMLElement) || child === rail || child.matches('.od-rail__scrim'))
        return
      previousInert.set(child, child.inert)
      child.inert = true
    })

    const focusable = () =>
      Array.from(
        railNode.querySelectorAll<HTMLElement>(
          'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.getClientRects().length > 0)

    const first = focusable()[0]
    first?.focus()

    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        setDrawerOpen(false)
        return
      }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) {
        event.preventDefault()
        railNode.focus()
        return
      }
      const firstItem = items[0]
      const lastItem = items[items.length - 1]
      if (
        event.shiftKey &&
        (document.activeElement === firstItem || !railNode.contains(document.activeElement))
      ) {
        event.preventDefault()
        lastItem.focus()
      } else if (
        !event.shiftKey &&
        (document.activeElement === lastItem || !railNode.contains(document.activeElement))
      ) {
        event.preventDefault()
        firstItem.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previousInert.forEach((wasInert, element) => {
        element.inert = wasInert
      })
      const opener = drawerOpener.current
      if (opener?.isConnected) opener.focus()
      drawerOpener.current = null
    }
  }, [drawerOpen, isMobile])

  const toggle = useCallback(() => {
    // One button drives both behaviours: on mobile it opens the drawer, on
    // desktop it collapses. Deciding here rather than in the component keeps
    // both shells from re-implementing the branch.
    if (isMobile)
      setDrawerOpen((open) => {
        if (!open && document.activeElement instanceof HTMLElement)
          drawerOpener.current = document.activeElement
        return !open
      })
    else setCollapsed((value) => !value)
  }, [isMobile])

  const closeDrawer = useCallback(() => setDrawerOpen(false), [])

  /** Value for the shell's data-rail attribute. */
  const railState = drawerOpen ? 'open' : collapsed ? 'collapsed' : 'expanded'

  return { collapsed, drawerOpen, isMobile, railState, toggle, closeDrawer }
}
