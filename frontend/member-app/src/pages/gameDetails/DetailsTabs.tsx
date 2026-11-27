import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'

export interface DetailsTab {
  id: string
  label: string
  content: ReactNode
}

/**
 * The library tools under the fold — versions, saves, cheats, mods, extras —
 * as one tabbed panel instead of a column of full-height sections.
 *
 * Stacked, those sections were most of the page: Cheats and Mods each open
 * with an inline form, so a title with every tool switched on scrolled for
 * three or four screens before reaching Extras. As tabs, the page is as tall
 * as the one tool you are looking at.
 *
 * Most panels decide for themselves whether to render (no saves, mods off, no
 * achievements…), and several decide after a fetch. So every panel stays
 * mounted, hidden when it is not the active tab, and a tab only appears once
 * its panel has rendered something. A MutationObserver keeps that honest as
 * panels fill in or empty out, and the whole strip disappears when none of
 * them has anything to show.
 *
 * Deep links still work: a `#updates` or `#cheats` hash (the action bar's
 * Update link uses the first) opens the tab that holds that anchor.
 */
export function DetailsTabs({ tabs }: { tabs: DetailsTab[] }) {
  const panelRefs = useRef(new Map<string, HTMLDivElement>())
  const tabRefs = useRef(new Map<string, HTMLButtonElement>())
  const [filled, setFilled] = useState<string[]>([])
  const [active, setActive] = useState<string | null>(null)
  const wantedHash = useRef<string | null>(null)
  const tabIds = tabs.map((tab) => tab.id).join('|')

  const measure = useCallback(() => {
    const next = tabs
      .map((tab) => tab.id)
      .filter((id) => (panelRefs.current.get(id)?.childElementCount ?? 0) > 0)
    setFilled((current) =>
      current.length === next.length && current.every((id, index) => id === next[index])
        ? current
        : next,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabIds])

  const openHashTarget = useCallback(() => {
    const hash = typeof window !== 'undefined' ? window.location.hash.slice(1) : ''
    if (!hash) return false
    for (const [id, panel] of panelRefs.current) {
      let target: Element | null = null
      try {
        target = panel.querySelector(`#${CSS.escape(hash)}`)
      } catch {
        target = null
      }
      if (target) {
        wantedHash.current = null
        setActive(id)
        requestAnimationFrame(() => target?.scrollIntoView?.({ block: 'start' }))
        return true
      }
    }
    wantedHash.current = hash
    return false
  }, [])

  useLayoutEffect(() => {
    measure()
    if (typeof MutationObserver === 'undefined') return undefined
    const observer = new MutationObserver(() => {
      measure()
      if (wantedHash.current) openHashTarget()
    })
    panelRefs.current.forEach((panel) => observer.observe(panel, { childList: true }))
    return () => observer.disconnect()
  }, [measure, openHashTarget])

  useEffect(() => {
    openHashTarget()
    window.addEventListener('hashchange', openHashTarget)
    return () => window.removeEventListener('hashchange', openHashTarget)
  }, [openHashTarget])

  // Keep the active tab pointing at something that exists.
  const current = active && filled.includes(active) ? active : (filled[0] ?? null)

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!current) return
    const index = filled.indexOf(current)
    let next = -1
    if (event.key === 'ArrowRight') next = (index + 1) % filled.length
    else if (event.key === 'ArrowLeft') next = (index - 1 + filled.length) % filled.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = filled.length - 1
    if (next < 0) return
    event.preventDefault()
    setActive(filled[next])
    tabRefs.current.get(filled[next])?.focus()
  }

  return (
    <div className="od-details-tabs" hidden={filled.length === 0}>
      <div className="od-details-tabs__list" role="tablist" aria-label="Library tools">
        {tabs
          .filter((tab) => filled.includes(tab.id))
          .map((tab) => (
            <button
              key={tab.id}
              className="od-details-tabs__tab"
              ref={(node) => {
                if (node) tabRefs.current.set(tab.id, node)
                else tabRefs.current.delete(tab.id)
              }}
              type="button"
              role="tab"
              id={`od-details-tab-${tab.id}`}
              aria-selected={tab.id === current}
              aria-controls={`od-details-tabpanel-${tab.id}`}
              tabIndex={tab.id === current ? 0 : -1}
              onClick={() => setActive(tab.id)}
              onKeyDown={onTabKeyDown}
            >
              {tab.label}
            </button>
          ))}
      </div>
      {tabs.map((tab) => (
        <div
          key={tab.id}
          ref={(node) => {
            if (node) panelRefs.current.set(tab.id, node)
            else panelRefs.current.delete(tab.id)
          }}
          role="tabpanel"
          id={`od-details-tabpanel-${tab.id}`}
          aria-labelledby={`od-details-tab-${tab.id}`}
          className="od-details-tabs__panel"
          hidden={tab.id !== current}
        >
          {tab.content}
        </div>
      ))}
    </div>
  )
}
