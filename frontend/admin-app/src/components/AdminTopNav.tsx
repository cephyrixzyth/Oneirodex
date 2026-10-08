import { useEffect, useId, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { useLocation } from 'react-router-dom'

import { AccountModal, openPreferencesModal, type AccountPanelId } from '@oneirodex/ui'
import AdminCommandPalette from './AdminCommandPalette'
import { resolveAdminPage } from './adminSection'
import './AdminTopNav.css'

const SECTION_HOME = {
  dashboard: { href: '/admin/dashboard', label: 'Dashboard' },
  libraries: { href: '/libraries', label: 'Libraries home' },
  extensions: { href: '/libraries', label: 'Libraries home' },
  scans: { href: '/scan_management', label: 'Scans home' },
  settings: { href: '/admin/settings', label: 'Settings home' },
  themes: { href: '/admin/themes', label: 'Themes' },
  help: { href: '/admin/help', label: 'Help' },
  announcements: { href: '/admin/announcements', label: 'Announcements' },
  support: { href: '/admin/support', label: 'Support inbox' },
  invites: { href: '/admin/invites', label: 'Invites' },
  users: { href: '/admin/users', label: 'Users home' },
  integrations: { href: '/admin/integrations', label: 'Integrations home' },
  system: { href: '/admin/ops', label: 'System home' },
  'system-danger': { href: '/admin/system/danger', label: 'Danger zone' },
  content: { href: '/admin/discovery_sections', label: 'Content home' },
  'settings-section': { href: '/admin/settings', label: 'Settings home' },
  generic: { href: '/admin/dashboard', label: 'Dashboard' },
}

/* Identity entries only — exits live on the rail (not duplicated here).
   Preferences opens the shared modal; Profile / tokens / password open the
   shared AccountModal so they stay inside the shell. */
const ACCOUNT_LINKS: {
  id: string
  href: string
  label: string
  modal?: AccountPanelId
  preferences?: boolean
}[] = [
  { id: 'profile', href: '/settings_profile_view', label: 'Profile', modal: 'profile' },
  { id: 'preferences', href: '/settings_panel', label: 'Preferences', preferences: true },
  { id: 'tokens', href: '/tokens', label: 'API tokens', modal: 'tokens' },
  { id: 'password', href: '/settings_password', label: 'Change Password', modal: 'password' },
]

function commandPaletteHint() {
  if (typeof navigator === 'undefined') return 'Ctrl+K'
  const platform = navigator.platform || ''
  const uaData = navigator.userAgentData
  const isMac = uaData?.platform === 'macOS' || /Mac|iPhone|iPad|iPod/i.test(platform)
  return isMac ? '⌘K' : 'Ctrl+K'
}

function readAdminIdentity() {
  if (typeof document === 'undefined') return { username: '', avatar: '' }
  const root = document.getElementById('admin-app-root')
  return {
    username: root?.dataset?.username || '',
    avatar: root?.dataset?.avatar || '',
  }
}

/**
 * Bar one for the admin shell, composed like the member bar (GT-B2 · GT-B31).
 */
export function AdminTopNav({
  onToggleRail,
  railState = 'expanded',
}: {
  onToggleRail?: () => void
  railState?: string
}) {
  const { pathname } = useLocation()
  const section = resolveAdminPage(pathname)
  const sectionHome = SECTION_HOME[section as keyof typeof SECTION_HOME] || SECTION_HOME.generic

  const [identity] = useState(readAdminIdentity)
  const [accountOpen, setAccountOpen] = useState(false)
  const [accountModal, setAccountModal] = useState<AccountPanelId | null>(null)
  const accountId = useId()
  const rootRef = useRef<HTMLElement | null>(null)
  const paletteHint = commandPaletteHint()

  useEffect(() => {
    if (!accountOpen) return undefined
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node | null)) setAccountOpen(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setAccountOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [accountOpen])

  async function handlePreferencesClick(event: ReactMouseEvent) {
    event.preventDefault()
    setAccountOpen(false)
    try {
      await openPreferencesModal()
    } catch {
      window.location.href = '/settings_panel'
    }
  }

  function openAccountModal(panel: AccountPanelId) {
    return (event: ReactMouseEvent) => {
      event.preventDefault()
      setAccountOpen(false)
      setAccountModal(panel)
    }
  }

  return (
    <>
      <header className="od-topbar" ref={rootRef}>
        <div className="od-topbar__start">
          <div className="od-cbtn-group od-topbar__cluster">
            <button
              type="button"
              className="od-cbtn od-topbar__rail-toggle"
              aria-label="Toggle navigation"
              aria-expanded={railState !== 'collapsed'}
              onClick={onToggleRail}
            >
              <span aria-hidden="true">☰</span>
            </button>
          </div>

          {railState === 'collapsed' ? (
            <span className="od-topbar__section">{sectionHome.label}</span>
          ) : null}
          {/* Left title/lede cluster (Ops, etc.) — beside the rail toggle. */}
          <div id="od-admin-topbar-title" className="od-topbar__title-slot" />
        </div>

        <div id="od-admin-topbar-slot" className="od-topbar__page" />

        <div className="od-topbar__actions">
          {/* Trail: Jinja contextbar summary (e.g. “60 libraries · N games”)
              so it lines up with the account control — member ContextBar’s
              trail slot. Page actions (AdminPageActions) stay in the centre. */}
          <div id="od-admin-topbar-trail" className="od-topbar__trail" />
          <div className="od-topnav__dropdown">
            <button
              type="button"
              className="od-cbtn od-topbar__account"
              aria-expanded={accountOpen}
              aria-controls={accountId}
              aria-label="Account menu"
              onClick={() => setAccountOpen((open) => !open)}
            >
              <span className="od-topbar__account-name">{identity.username || 'Account'}</span>
              {identity.avatar ? (
                <img
                  className="od-topbar__account-avatar"
                  src={
                    identity.avatar.startsWith('/') ? identity.avatar : `/static/${identity.avatar}`
                  }
                  alt=""
                  width={22}
                  height={22}
                />
              ) : (
                <span aria-hidden="true">👤</span>
              )}
            </button>
            {accountOpen ? (
              <div className="od-topnav__dropdown-panel od-menu-surface" id={accountId} role="menu">
                {identity.username ? (
                  <div className="od-topnav__username">{identity.username}</div>
                ) : null}
                <button
                  type="button"
                  role="menuitem"
                  className="od-topnav__palette-hint"
                  onClick={() => {
                    setAccountOpen(false)
                    document.dispatchEvent(new CustomEvent('od-admin-palette:open'))
                  }}
                >
                  Search everything <kbd>{paletteHint}</kbd>
                </button>
                {ACCOUNT_LINKS.map((link) => {
                  if (link.modal) {
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

        <AdminCommandPalette />
      </header>

      <AccountModal panel={accountModal} onClose={() => setAccountModal(null)} />
    </>
  )
}
