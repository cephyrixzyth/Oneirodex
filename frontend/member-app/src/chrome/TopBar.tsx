import { useEffect, useId, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { AccountModal, useShellConfig } from '@oneirodex/ui'

import { TOPBAR_LEAD_ID, TOPBAR_SLOT_ID, TOPBAR_TITLE_ID, TOPBAR_TRAIL_ID } from './ContextBar'
import { IconMenu, IconUser } from './icons'
import { TileSizeControl } from './TileSizeControl'
import { getPageTitle, hasTileSizeControl } from './navConfig'
import { openPreferencesModal } from '../api/preferences'

/**
 * Bar one, reduced to page scope (GT-B2).
 *
 * The rail owns identity and destinations now, so everything this bar used to
 * carry for navigation is gone: brand, the five primary links, the breadcrumb
 * strip, and the eighteen-item "More" dropdown. What remains is the set of
 * things that belong to the *current page* rather than to the app — search,
 * tile size, account — plus the control that opens the rail on mobile.
 *
 * Deliberately not a a wrapper around TopNav: keeping the old component and
 * hiding parts of it with props is how a component ends up with four layout
 * modes and no clear owner. TopNav stays in the tree only until the Jinja
 * pages that still render its markup are migrated.
 */

/* `modal` entries open an AccountModal panel instead of navigating.
   Only Logout still leaves the app, because it has to. Preferences keeps its
   own existing modal — it was already one, and it is Jinja-rendered. */
const ACCOUNT_LINKS = [
  { id: 'profile', href: '/settings_profile_view', label: 'Profile', modal: 'profile' },
  { id: 'preferences', href: '/settings_panel', label: 'Preferences', preferences: true },
  { id: 'tokens', href: '/tokens', label: 'API tokens', modal: 'tokens' },
  { id: 'password', href: '/settings_password', label: 'Change Password', modal: 'password' },
  { id: 'logout', href: '/logout', label: 'Logout' },
]

function commandPaletteHint() {
  if (typeof navigator === 'undefined') return 'Ctrl+K'
  const platform = navigator.platform || ''
  const uaData = navigator.userAgentData
  const isMac = uaData?.platform === 'macOS' || /Mac|iPhone|iPad|iPod/i.test(platform)
  return isMac ? '⌘K' : 'Ctrl+K'
}

export function TopBar({
  tileSize,
  onTileSizeChange,
  onOpenCommandPalette,
  onToggleRail,
  railState = 'expanded',
  views = null,
}: LooseProps) {
  const shellConfig = useShellConfig() as LooseProps
  const {
    username = '',
    avatar = '',
    showTrailers,
    showHelp,
    enableVr,
    enableActivity,
  } = shellConfig
  const { pathname } = useLocation()
  const pageTitle = getPageTitle(pathname, { showTrailers, showHelp, enableVr, enableActivity })
  const showTileSize = hasTileSizeControl(pathname)
  const [accountOpen, setAccountOpen] = useState(false)
  const [accountModal, setAccountModal] = useState<any>(null)
  const accountId = useId()
  const rootRef = useRef<any>(null)
  const paletteHint = commandPaletteHint()

  useEffect(() => {
    if (!accountOpen) return undefined
    function onPointerDown(event: any) {
      if (!rootRef.current?.contains(event.target)) setAccountOpen(false)
    }
    function onKey(event: any) {
      if (event.key === 'Escape') setAccountOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [accountOpen])

  async function handlePreferencesClick(event: any) {
    event.preventDefault()
    setAccountOpen(false)
    try {
      await openPreferencesModal()
    } catch {
      window.location.href = '/settings_panel'
    }
  }

  /* Profile opens the modal directly.
     It used to open a right-hand drawer whose entire content was a list of
     links to the same five panels the modal already switches between — a menu
     in front of a menu, with the drawer adding nothing but a second click and a
     second visual language. The drawer is gone; every entry here lands on its
     panel. */
  function openAccountModal(panel: any) {
    return (event: any) => {
      event.preventDefault()
      setAccountOpen(false)
      setAccountModal(panel)
    }
  }

  return (
    <>
      <header className="od-topbar" ref={rootRef}>
        {/* The rail has three states and this button drives all of them, so
            `=== 'open'` was the wrong test: 'open' is the mobile drawer only,
            which left aria-expanded permanently false on desktop — announcing a
            collapsed rail while it sat there expanded with its labels showing.
            Shown is 'open' or 'expanded'; the one state that is not is
            'collapsed'. partials/topbar.html has always had this right. */}
        {/* Start group. Wrapped, and paired with an equally-growing actions
            group in od-shell.css, so the centre slot lands on the *page's*
            midpoint rather than on the midpoint of whatever width the two sides
            happened to leave. Unwrapped, every side control that appeared or
            changed width nudged the view switcher off centre. */}
        <div className="od-topbar__start">
          {/* Adjacent chromeless controls, not one outlined cluster.
              Open the nav, narrow the list — the same kind of job, done to the
              same list — so they sit together at the start of the bar. They
              were reported as a shared outline around hamburger + Filters;
              `.od-cbtn-group` stays for slot plumbing, but the pair no longer
              shares an edge. Nothing goes between them: the page name used to,
              which pushed Filters to a different x position on every page. */}
          <div className="od-cbtn-group od-topbar__cluster">
            <button
              type="button"
              className="od-cbtn od-topbar__rail-toggle"
              aria-label="Toggle navigation"
              aria-expanded={railState !== 'collapsed'}
              onClick={onToggleRail}
            >
              <IconMenu />
            </button>

            {/* Lead slot: Filters, immediately after the rail toggle. */}
            <div id={TOPBAR_LEAD_ID} className="od-topbar__lead" />
          </div>

          {/* Where a page that knows its own name puts it — a Discover row's
              "see all" page, whose title is data rather than a route. Outside
              the cluster so it reads as a label beside the controls rather
              than as a third button in the group. */}
          <div id={TOPBAR_TITLE_ID} className="od-topbar__title-slot" />

          {/* The page name. It used to render only on a collapsed rail, on
              the reasoning that an expanded rail already names the active
              entry a few pixels to the left. That left the page with NO
              heading at all: the rail entry is a nav link, and the page's own
              h1 is retired under the v2 chrome, so `h1..h6` counted ZERO on 15
              routes. It is the page heading now — always present, so heading
              navigation works whatever the rail is doing.
              When ContextBar portals its own title into the lead slot,
              od-shell.css hides this copy with `display: none`, which removes
              it from the a11y tree too, so exactly one heading is exposed. */}
          {pageTitle ? <h1 className="od-topbar__section">{pageTitle}</h1> : null}
        </div>

        {views ? <div className="od-topbar__views">{views}</div> : null}

        {/* Centre slot: the page's own views and actions. Centred and growing
            outward from the middle, so adding a view keeps the strip balanced
            instead of pushing everything right. ContextBar portals here. */}
        <div id={TOPBAR_SLOT_ID} className="od-topbar__page" />

        <div className="od-topbar__actions">
          {/* The search field is gone from the bar (GT-B16).
              Typing into the library's own filter is how you search a library,
              and a second search affordance in the chrome bought nothing while
              costing permanent width. ⌘K still opens the palette — the shortcut
              is listed in the account menu so it stays discoverable. */}

          {/* Slider, then count, then account. The count used to read first,
              on the argument that a label after its instrument reads as a value
              readout — but the slider collapses to a single dot at rest, and a
              collapsed control leading the group left its reserved width as a
              visible hole between the centre slot and the count. With the
              slider first and right-aligned inside its own reserve (see
              TileSizeControl.css), the dot rests against the count, the reserve
              falls in the bar's existing slack where nothing can see it, and
              the slider opens leftward into that slack without moving the count
              or the account button.

              Rendered only where it changes something. `--od-tile-min` is read
              by the game grid and by the card geometry derived from it; every
              other page ignored it, so the slider sat in the bar on Help,
              Notifications, Calendar and the rest doing nothing but saving a
              preference. See hasTileSizeControl. On those pages the count
              simply leads the group, which is where it used to be anyway. */}
          {/* Titles moved to Preferences → Look & density, beside tile size.
              It was a labelled checkbox holding permanent width in the bar
              for a setting a member changes once and then leaves alone, and
              it sat next to the slider it is not — one is a continuous
              control you drag while watching the grid, the other is a
              one-shot preference. The form field it writes was always in
              `modal_preferences.html`'s form; only the control moved. */}
          {showTileSize ? (
            <TileSizeControl
              value={tileSize || shellConfig.tileSize || '50'}
              onChange={onTileSizeChange}
              shellConfig={shellConfig}
            />
          ) : null}

          {/* Trail slot: how much is here. Still grouped with the control that
              changes it — both answer "how much am I looking at". */}
          <div id={TOPBAR_TRAIL_ID} className="od-topbar__trail" />

          <div className="od-topnav__dropdown">
            {/* Who you are, then your face.
                It was a generic person glyph followed by a name — the one
                identity control in the product, rendered identically for every
                member, next to an avatar they had chosen and never saw. The
                name leads and the avatar closes the button, which is the order
                the eye reads a signed-in control in: label first, portrait at
                the edge nearest the window corner.

                Still `.od-cbtn`, so it is the same button as everything else in
                the bar; the avatar is sized to the control rather than the
                other way round. */}
            <button
              type="button"
              className="od-cbtn od-topbar__account"
              aria-expanded={accountOpen}
              aria-controls={accountId}
              aria-label="Account menu"
              onClick={() => setAccountOpen((open) => !open)}
            >
              <span className="od-topbar__account-name">{username || 'Account'}</span>
              {avatar ? (
                <img
                  className="od-topbar__account-avatar"
                  src={avatar.startsWith('/') ? avatar : `/static/${avatar}`}
                  alt=""
                  width={22}
                  height={22}
                />
              ) : (
                <IconUser />
              )}
            </button>
            {accountOpen ? (
              <div className="od-topnav__dropdown-panel od-menu-surface" id={accountId} role="menu">
                {username ? <div className="od-topnav__username">{username}</div> : null}
                {/* Only remaining home for the palette hint now the bar's
                    search button is gone. CommandPalette binds ⌘K itself, so
                    this is discoverability, not the trigger. */}
                <button
                  type="button"
                  role="menuitem"
                  className="od-topnav__palette-hint"
                  onClick={() => {
                    setAccountOpen(false)
                    onOpenCommandPalette?.()
                  }}
                >
                  Search everything <kbd>{paletteHint}</kbd>
                </button>
                {ACCOUNT_LINKS.map((link) => {
                  if (link.modal) {
                    // Still an <a href>: middle-click and "open in new tab"
                    // land on the server-rendered page, which is the fallback.
                    return (
                      <a
                        key={link.id}
                        href={link.href}
                        role="menuitem"
                        onClick={openAccountModal(link.modal)}
                      >
                        {link.label}
                      </a>
                    )
                  }
                  if (link.preferences) {
                    return (
                      <a
                        key={link.id}
                        href={link.href}
                        role="menuitem"
                        onClick={handlePreferencesClick}
                      >
                        {link.label}
                      </a>
                    )
                  }
                  return (
                    <a
                      key={link.id}
                      href={link.href}
                      role="menuitem"
                      onClick={() => setAccountOpen(false)}
                    >
                      {link.label}
                    </a>
                  )
                })}
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <AccountModal panel={accountModal} onClose={() => setAccountModal(null)} />
    </>
  )
}

export default TopBar
