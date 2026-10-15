import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { AdminPageActions } from './AdminPageActions'
import { findSubSection } from './navConfig'
import { RailIcon } from './railIcons'

const SECTION_HUBS: Record<string, { href: string; label: string }> = {
  settings: { href: '/admin/settings', label: 'All settings' },
  integrations: { href: '/admin/integrations', label: 'Overview' },
}

/**
 * Top-bar buttons for a Settings / Integrations sub-section: the children of
 * the sub-section the rail has open, one icon button each, plus a way back to
 * the section's hub page. Mounted once in the shell so every page in those
 * sections — including Jinja-backed ones — gets the same bar.
 */
export function SectionTopNav() {
  const { pathname, hash } = useLocation()
  const [activeLink, setActiveLink] = useState<HTMLAnchorElement | null>(null)
  useEffect(() => {
    if (!activeLink) return
    const strip = activeLink.closest<HTMLElement>('.od-cbtn-group, .od-admin-actions-row')
    if (!strip) return
    // Only move this horizontal strip. scrollIntoView can move the document,
    // other ancestors, and keyboard focus away from the user's current task.
    function reveal() {
      if (!strip || !activeLink || strip.scrollWidth <= strip.clientWidth) return
      const viewport = strip.getBoundingClientRect()
      const link = activeLink.getBoundingClientRect()
      const left = viewport.left + strip.clientLeft
      const right = left + strip.clientWidth
      const delta =
        link.left < left ? link.left - left : link.right > right ? link.right - right : 0
      if (delta) strip.scrollLeft = Math.max(0, strip.scrollLeft + delta)
    }
    const frame = requestAnimationFrame(reveal)
    window.addEventListener('resize', reveal)
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(reveal) : null
    observer?.observe(strip)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', reveal)
      observer?.disconnect()
    }
  }, [activeLink, pathname, hash])
  // The Integrations overview already lists every destination as grouped rows.
  // Adding the same links to the top bar when a row's hash is active duplicates
  // the Metadata & art buttons on that page.
  if ((pathname || '').replace(/\/+$/, '') === '/admin/integrations') return null
  const here = findSubSection(pathname, hash)
  if (!here) return null
  const hub = SECTION_HUBS[here.sectionId]

  return (
    <AdminPageActions label={`${here.sub.title} pages`}>
      {hub ? (
        <a className="od-cbtn od-cbtn--section" href={hub.href}>
          {hub.label}
        </a>
      ) : null}
      {here.sub.items.map((item) => {
        const active = item.to === here.item.to
        return (
          <a
            ref={active ? setActiveLink : undefined}
            key={item.to}
            className={`od-cbtn od-cbtn--section${active ? ' is-active' : ''}`}
            href={item.to}
            aria-current={active ? 'page' : undefined}
            title={item.blurb}
          >
            <RailIcon name={item.icon} size={16} />
            <span>{item.title}</span>
          </a>
        )
      })}
    </AdminPageActions>
  )
}
