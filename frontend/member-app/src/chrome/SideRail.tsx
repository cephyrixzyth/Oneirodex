import { useCallback, useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useShellConfig, useViewer } from '@oneirodex/ui'

import { RailIcon } from './railIcons'
import { PRIMARY_GROUP, getMoreGroups, getPrimaryLinks } from './navConfig'

const COLLAPSED_GROUPS_KEY = 'od.rail.collapsedGroups'

/**
 * Which rail groups the member has folded away, remembered across sessions.
 *
 * Twenty-three destinations is a long column and most sessions live in one part
 * of it. Persisted because a fold you have to redo on every page load is worse
 * than no fold at all. Storage failures are swallowed: private-mode browsers
 * throw on `localStorage`, and losing the preference must not cost the rail.
 */
function useCollapsedGroups() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      const raw = window.localStorage.getItem(COLLAPSED_GROUPS_KEY)
      return new Set(raw ? JSON.parse(raw) : [])
    } catch {
      return new Set()
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_GROUPS_KEY, JSON.stringify([...collapsed]))
    } catch {
      // Preference only — the rail works either way.
    }
  }, [collapsed])

  const toggle = useCallback((id: any) => {
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
 * Left navigation rail for the member shell (GT-B2).
 *
 * Replaces the five-slot top bar plus its eighteen-item "More" menu. Every
 * destination is present and grouped; nothing is behind an overflow. The groups
 * are the ones getMoreGroups already defined for the old menu — that grouping
 * was sound, it was just being applied to a popover that hid it.
 *
 * Styling lives entirely in the theme's od-shell.css so the admin shell and
 * legacy Jinja pages render the same rail from the same source (the UIR-4
 * pattern). This component contributes no CSS of its own.
 */
export function SideRail({ railState = 'expanded', onNavigate, onCloseDrawer }: LooseProps) {
  const { isAdmin } = useViewer()
  const {
    showTrailers = false,
    showHelp = false,
    enableVr = false,
    enableActivity = true,
  } = useShellConfig()

  const primary = getPrimaryLinks()
  const groups = getMoreGroups({ showTrailers, showHelp, enableVr, enableActivity })
  const collapsed = railState === 'collapsed'
  const { pathname } = useLocation()
  const [filtersHidden, setFiltersHidden] = useState(false)
  const [collapsedGroups, toggleGroup] = useCollapsedGroups()
  // Same rule the other groups follow: never fold while the rail is collapsed,
  // because the headings are visually hidden there and a folded group would be
  // destinations that vanished with no visible control to bring them back.
  const primaryFolded = !collapsed && collapsedGroups.has(PRIMARY_GROUP.id)

  // Clicking Library while already on Library used to be a no-op. It is the
  // obvious place to put the filter panel's show/hide, and it is where it used
  // to live before the panel moved into the rail (W27-A6). Hiding the slot
  // rather than the filters themselves keeps LibraryApp's portal working — the
  // rail never has to know what a filter is.
  const onLibraryClick = (event: any) => {
    if (pathname === '/library' || pathname.startsWith('/library/')) {
      event.preventDefault()
      setFiltersHidden((hidden) => !hidden)
      return
    }
    onCloseDrawer?.()
  }

  function renderLink(link: any) {
    // Action entries (Chat, Friends) open panels rather than routing. They are
    // still destinations from the member's point of view, so they belong in the
    // rail next to the routed ones rather than in a separate control.
    if (link.action) {
      return (
        <li key={link.id}>
          <button
            type="button"
            className="od-rail__link"
            /* Which destination this row is, for the stylesheet.
               Every icon animated identically on hover — one shared pop — so
               the motion said "you are on a row" rather than "you are on
               Favorites". od-shell.css keys a per-destination animation off
               this attribute: the heart beats, the download arrow falls, the
               calendar leaf turns. */
            data-rail-item={link.id}
            onClick={() => {
              onNavigate?.(link)
              onCloseDrawer?.()
            }}
          >
            <span className="od-rail__icon" aria-hidden="true">
              <RailIcon name={link.id} />
            </span>
            <span className="od-rail__label">{link.label}</span>
          </button>
        </li>
      )
    }

    return (
      <li key={link.id}>
        <NavLink
          to={link.to}
          className={({ isActive }) => (isActive ? 'od-rail__link is-active' : 'od-rail__link')}
          data-rail-item={link.id}
          aria-expanded={link.id === 'library' ? !filtersHidden : undefined}
          onClick={link.id === 'library' ? onLibraryClick : onCloseDrawer}
          // Collapsed hides the visible label, so the title attribute is the
          // only thing left that names the target on hover.
          title={collapsed ? link.label : undefined}
        >
          <span className="od-rail__icon" aria-hidden="true">
            <RailIcon name={link.id} />
          </span>
          <span className="od-rail__label">{link.label}</span>
        </NavLink>
      </li>
    )
  }

  // Container, not the landmark — see AdminSideRail: a brand link inside
  // <nav> is announced as a destination and shadows real ones in queries.
  return (
    <div className="od-rail">
      {/* Mark only, no wordmark (W28). The glyph is the brand; the word beside
          it was a second answer to the same question and it capped the mark at
          rail-icon size. `od-rail__brand-text` stays in the markup and is
          hidden in CSS — it is the link's accessible name. */}
      <a className="od-rail__brand od-rail__brand--mark-only" href="/discover">
        {/* Painted from a mask so it follows the theme — see .od-brand-mark. */}
        <span className="od-rail__mark od-brand-mark" aria-hidden="true" />
        <span className="od-rail__brand-text">Oneirodex</span>
      </a>

      <nav className="od-rail__nav" aria-label="Primary">
        {/* The five core destinations, under the product's own name.
            Foldable like every other group — it was the one block of the rail
            that could not be put away, and on a short screen it was also the
            block between you and the groups you had already chosen to keep
            open. The heading uses the same toggle as the rest, so there is one
            fold interaction in the rail rather than two. */}
        <ul className="od-rail__group od-rail__list">
          <li className="od-rail__group-label">
            <button
              type="button"
              className="od-rail__group-toggle"
              aria-expanded={!primaryFolded}
              onClick={() => toggleGroup(PRIMARY_GROUP.id)}
            >
              <span className="od-rail__group-caret" aria-hidden="true" />
              <span>{PRIMARY_GROUP.label}</span>
            </button>
          </li>
          {primaryFolded
            ? null
            : primary.map((link) => (
                <li key={link.id} className="od-rail__item">
                  <ul className="od-rail__list">{renderLink(link)}</ul>
                  {/* Slot for the active section's own controls (GT-B4).
                  Library filters used to be a second 17.5rem aside next to the
                  rail — two left-hand panels, which is what read as broken.
                  LibraryApp portals its FilterBar in here instead, so filters
                  live under the destination they belong to and the content pane
                  gets the width back. A portal rather than props: the shell
                  should not have to know what a filter is. */}
                  {link.id === 'library' ? (
                    <div
                      id="od-rail-slot"
                      className={`od-rail__slot${filtersHidden ? ' is-hidden' : ''}`}
                    />
                  ) : null}
                </li>
              ))}
        </ul>

        {groups.map((group) => {
          // Never fold a group while the rail is collapsed: the headings are
          // visually hidden there, so a folded group would be destinations that
          // disappeared with no visible control to bring them back.
          const folded = !collapsed && collapsedGroups.has(group.id)
          return (
            <ul className="od-rail__group od-rail__list" key={group.id}>
              <li className="od-rail__group-label">
                <button
                  type="button"
                  className="od-rail__group-toggle"
                  aria-expanded={!folded}
                  onClick={() => toggleGroup(group.id)}
                >
                  <span className="od-rail__group-caret" aria-hidden="true" />
                  <span>{group.label}</span>
                </button>
              </li>
              {folded ? null : group.links.map(renderLink)}
            </ul>
          )
        })}

        {isAdmin ? (
          <ul className="od-rail__group od-rail__list">
            <li className="od-rail__group-label" aria-hidden="true">
              Manage
            </li>
            <li>
              {/* Full page load: admin is a separate bundle, not a route here. */}
              <a
                className="od-rail__link"
                data-rail-item="admin"
                href="/admin/dashboard"
                title={collapsed ? 'Admin' : undefined}
              >
                <span className="od-rail__icon" aria-hidden="true">
                  <RailIcon name="admin" />
                </span>
                <span className="od-rail__label">Admin</span>
              </a>
            </li>
          </ul>
        ) : null}
      </nav>
    </div>
  )
}

export default SideRail
