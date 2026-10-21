import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

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
  const { pathname, search, hash } = useLocation()
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
  const scanView =
    pathname === '/admin/scan-controls'
      ? 'auto'
      : pathname === '/admin/scan-jobs'
        ? 'jobs'
        : pathname.startsWith('/scan_management')
          ? new URLSearchParams(search).get('active_tab') || 'auto'
          : ''
  if (['auto', 'manual', 'jobs'].includes(scanView)) {
    const scanPages = [
      { id: 'auto', href: '/scan_management?active_tab=auto', label: 'Scanning' },
      {
        id: 'manual',
        href: '/scan_management?active_tab=manual#manual-identify',
        label: 'Manual identify',
      },
      { id: 'jobs', href: '/scan_management?active_tab=jobs', label: 'Scan jobs' },
    ]
    return (
      <AdminPageActions label="Scan pages">
        {scanPages.map((item) => (
          <Link
            key={item.id}
            className={`od-cbtn od-cbtn--section${scanView === item.id ? ' is-active' : ''}`}
            to={item.href}
            aria-current={
              scanView === item.id ? (item.id === 'manual' ? 'location' : 'page') : undefined
            }
          >
            {item.label}
          </Link>
        ))}
      </AdminPageActions>
    )
  }
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
        <Link className="od-cbtn od-cbtn--section" to={hub.href}>
          {hub.label}
        </Link>
      ) : null}
      {here.sub.items.map((item) => {
        const active = item.to === here.item.to
        return (
          <Link
            ref={active ? setActiveLink : undefined}
            key={item.to}
            className={`od-cbtn od-cbtn--section${active ? ' is-active' : ''}`}
            to={item.to}
            aria-current={active ? 'page' : undefined}
            title={item.blurb}
          >
            <RailIcon name={item.icon} size={16} />
            <span>{item.title}</span>
          </Link>
        )
      })}
    </AdminPageActions>
  )
}
