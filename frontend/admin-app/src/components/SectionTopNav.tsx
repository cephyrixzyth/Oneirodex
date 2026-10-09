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
