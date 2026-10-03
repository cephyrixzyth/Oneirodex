import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

import {
  ADMIN_NAV,
  findSubSection,
  hubIcon,
  railDestinations,
  railSubSections,
  resolveNavSection,
} from './navConfig'
import { RailIcon } from './railIcons'

const COLLAPSED_SECTIONS_KEY = 'od.admin.rail.collapsedSections'

interface AdminNavLink {
  id: string
  path: string
  label: string
}

/**
 * Which admin LHN sections the operator has folded away.
 *
 * Defaults to every section that has hub links *except* the active one, so the
 * rail opens focused on where you are. After the first visit, the set is
 * whatever the operator last chose — folding must stick across pages.
 */
function useCollapsedSections(activeSectionId: string | null) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try {
      const raw = window.localStorage.getItem(COLLAPSED_SECTIONS_KEY)
      if (raw) return new Set(JSON.parse(raw))
    } catch {
      // Preference only.
    }
    const initial = new Set<string>()
    for (const link of ADMIN_NAV) {
      if (!railDestinations(link.id).length && !railSubSections(link.id).length) continue
      if (link.id === activeSectionId) continue
      initial.add(link.id)
    }
    return initial
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_SECTIONS_KEY, JSON.stringify([...collapsed]))
    } catch {
      // Preference only — the rail works either way.
    }
  }, [collapsed])

  // Opening a section's page expands that section once, without re-folding
  // others the operator already opened.
  useEffect(() => {
    if (!activeSectionId) return
    setCollapsed((previous) => {
      if (!previous.has(activeSectionId)) return previous
      const next = new Set(previous)
      next.delete(activeSectionId)
      return next
    })
  }, [activeSectionId])

  const toggle = useCallback((id: string) => {
    setCollapsed((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  return [collapsed, toggle] as const
}

/**
 * Left navigation rail for the admin shell.
 *
 * Hub sections use the member Oneirodex fold: muted uppercase
 * `.od-rail__group-toggle` headings (caret + label). Destinations are the
 * indented, icon-led sub-links underneath. Settings and Integrations unfold into
 * their sub-sections; those pages' children are buttons in the top bar. Dashboard and icon-only rail stay plain
 * destination links with icons.
 */
export function AdminSideRail({
  railState = 'expanded',
  onCloseDrawer,
}: {
  railState?: string
  onCloseDrawer?: () => void
}) {
  const { pathname, search, hash } = useLocation()
  const iconOnly = railState === 'collapsed'
  const ownedSection = resolveNavSection(pathname)
  const [collapsedSections, toggleSection] = useCollapsedSections(ownedSection)

  function isActiveSection(link: AdminNavLink) {
    if (ownedSection) {
      return link.id === ownedSection
    }
    if (link.id === 'content') {
      return (
        pathname.includes('announcement') ||
        pathname.includes('discovery') ||
        pathname.includes('newsletter') ||
        pathname.includes('attract')
      )
    }
    if (link.path === '/admin/dashboard') {
      return pathname === '/admin/dashboard' || pathname === '/admin' || pathname === '/admin/'
    }
    const base = link.path.split('?')[0]
    return pathname === base || pathname.startsWith(`${base}/`)
  }

  function isActiveSub(href: string | undefined, label?: string) {
    if (!href) return false
    try {
      const u = new URL(href, window.location.origin)
      if (pathname !== u.pathname) return false
      // Scan covers auto + manual; THN picks the mode.
      if (label === 'Scan' && u.pathname === '/scan_management') {
        const tab = new URLSearchParams(search).get('active_tab')
        return tab === 'auto' || tab === 'manual' || tab == null
      }
      const wantTab = u.searchParams.get('active_tab')
      if (wantTab != null) {
        return new URLSearchParams(search).get('active_tab') === wantTab
      }
      return true
    } catch {
      return false
    }
  }

  function destinationLink(link: AdminNavLink, { active }: { active?: boolean } = {}) {
    const linkClass = active ? 'od-rail__link is-active' : 'od-rail__link'
    return (
      <li key={link.id}>
        <a
          className={linkClass}
          href={link.path}
          data-rail-item={link.id}
          onClick={onCloseDrawer}
          title={iconOnly ? link.label : undefined}
          aria-current={active ? 'page' : undefined}
        >
          <span className="od-rail__icon" aria-hidden="true">
            <RailIcon name={link.id} />
          </span>
          <span className="od-rail__label">{link.label}</span>
        </a>
      </li>
    )
  }

  return (
    <div className="od-rail">
      <a className="od-rail__brand od-rail__brand--mark-only" href="/admin/dashboard">
        <span className="od-rail__mark od-brand-mark" aria-hidden="true" />
        <span className="od-rail__brand-text">Oneirodex Admin</span>
      </a>

      <nav className="od-rail__nav" aria-label="Admin">
        {ADMIN_NAV.map((link) => {
          const active = isActiveSection(link)
          const subs = railDestinations(link.id)
          const groups = railSubSections(link.id)
          const hasSubs = subs.length > 0 || groups.length > 0

          // Icon-only rail, or a section with no hub list: plain destination.
          if (iconOnly || !hasSubs) {
            return (
              <ul key={link.id} className="od-rail__group od-rail__list">
                {destinationLink(link, { active })}
              </ul>
            )
          }

          const folded = collapsedSections.has(link.id)
          return (
            <ul key={link.id} className="od-rail__group od-rail__list">
              <li className="od-rail__group-label">
                <button
                  type="button"
                  className="od-rail__group-toggle"
                  aria-expanded={!folded}
                  onClick={() => toggleSection(link.id)}
                >
                  <span className="od-rail__group-caret" aria-hidden="true" />
                  <span>{link.label}</span>
                </button>
              </li>
              {folded
                ? null
                : groups.map((group) => {
                    const here = findSubSection(pathname, hash)
                    const groupActive = here?.sub.id === group.id && here.sectionId === link.id
                    return (
                      <li key={`${link.id}:${group.id}`}>
                        <a
                          className={
                            groupActive
                              ? 'od-rail__link od-rail__link--sub is-active'
                              : 'od-rail__link od-rail__link--sub'
                          }
                          href={group.items[0].to}
                          data-rail-item={group.icon}
                          onClick={onCloseDrawer}
                          aria-current={groupActive ? 'page' : undefined}
                        >
                          <span className="od-rail__icon" aria-hidden="true">
                            <RailIcon name={group.icon} />
                          </span>
                          <span className="od-rail__label">{group.title}</span>
                        </a>
                      </li>
                    )
                  })}
              {folded
                ? null
                : subs.map((sub) => {
                    const subActive = isActiveSub(sub.href, sub.label)
                    return (
                      <li key={`${link.id}:${sub.href}:${sub.label}`}>
                        <a
                          className={
                            subActive
                              ? 'od-rail__link od-rail__link--sub is-active'
                              : 'od-rail__link od-rail__link--sub'
                          }
                          href={sub.href}
                          onClick={onCloseDrawer}
                          aria-current={subActive ? 'page' : undefined}
                        >
                          <span className="od-rail__icon" aria-hidden="true">
                            <RailIcon name={hubIcon(sub.label)} />
                          </span>
                          <span className="od-rail__label">{sub.label}</span>
                        </a>
                      </li>
                    )
                  })}
            </ul>
          )
        })}

        <ul className="od-rail__group od-rail__list">
          <li className="od-rail__group-label" aria-hidden="true">
            Member
          </li>
          <li>
            <a
              className="od-rail__link"
              data-rail-item="library"
              href="/library"
              title={iconOnly ? 'Library' : undefined}
            >
              <span className="od-rail__icon" aria-hidden="true">
                <RailIcon name="library" />
              </span>
              <span className="od-rail__label">Library</span>
            </a>
          </li>
          <li>
            <a
              className="od-rail__link"
              data-rail-item="logout"
              href="/logout"
              title={iconOnly ? 'Log out' : undefined}
            >
              <span className="od-rail__icon" aria-hidden="true">
                <RailIcon name="logout" />
              </span>
              <span className="od-rail__label">Log out</span>
            </a>
          </li>
        </ul>
      </nav>
    </div>
  )
}

export default AdminSideRail
