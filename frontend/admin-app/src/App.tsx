import { useEffect } from 'react'
import { useRailState } from '@oneirodex/ui'
import { AdminSideRail } from './components/AdminSideRail'
import { AdminTopNav } from './components/AdminTopNav'
import { SectionTopNav } from './components/SectionTopNav'
import { AdminRoutes } from './components/AdminRoutes'
import { useAdminShellFrame } from './hooks/useAdminShellFrame'
import { useLegacyContextbarPortal } from './hooks/useLegacyContextbarPortal'
import { useLibrariesContextbarUnfurl } from './hooks/useLibrariesContextbarUnfurl'
import { useLibrariesPanelMount } from './hooks/useLibrariesPanelMount'
import { useLibraryScanToasts } from './hooks/useLibraryScanToasts'
import './ops.css'

/**
 * Legacy fallback only — see resolveRenderMode.
 *
 * Kept for templates that have not yet declared data-admin-render. Do not add
 * selectors here; migrate the template to `spa` or `legacy` instead.
 */
function hasLegacyBody() {
  const legacy = document.getElementById('admin-legacy-content')
  if (!legacy) {
    return false
  }
  const text = (legacy.textContent || '').replace(/\s+/g, ' ').trim()
  if (text.length < 40) {
    return false
  }
  return Boolean(
    legacy.querySelector(
      'form, table, .od-adminpage, .od-admin-card, .settings-shell, .settings-shell-cards, .settings-shell-card, .container-settings-dashboard, .container, .card, .datatable, #proposalsList, .admin-page, .admin-section',
    ),
  )
}

/**
 * Which body should render (GT-A3).
 *
 * The template declares intent via `data-admin-render` on #admin-app-root.
 * Previously this was inferred at runtime by sniffing the Jinja body for
 * `form, table, .card, .container, …` — so an unrelated markup change in a
 * template could silently delete the React page for that route, and whether a
 * given admin screen looked React or Bootstrap was not knowable from the source.
 *
 * `auto` preserves the old behaviour for templates not yet migrated, so this
 * can land without touching all 47 admin templates at once.
 *
 * @returns {'spa'|'legacy'} which body to render
 */
export function resolveRenderMode(root = document.getElementById('admin-app-root')) {
  const declared = root?.dataset?.adminRender

  if (declared === 'spa') return 'spa'
  if (declared === 'legacy') return 'legacy'

  if (declared && declared !== 'auto' && typeof console !== 'undefined') {
    console.warn(`[admin] unknown data-admin-render="${declared}" — falling back to auto detection`)
  }

  return hasLegacyBody() ? 'legacy' : 'spa'
}

export function App() {
  const legacy = resolveRenderMode() === 'legacy'
  const { railState, drawerOpen, toggle: toggleRail, closeDrawer } = useRailState()

  useAdminShellFrame(railState)
  useLibraryScanToasts({ enabled: true })
  // Jinja chrome.contextbar → thin top bar (member ContextBar parity).
  useLegacyContextbarPortal(legacy)
  useLibrariesContextbarUnfurl(legacy)
  useLibrariesPanelMount(legacy)

  // SPA pages: park #admin-legacy-content so it cannot steal the main grid
  // cell (whitespace used to keep it painted as a dead column). Legacy Jinja
  // pages keep it visible — that is their body.
  useEffect(() => {
    const node = document.getElementById('admin-legacy-content')
    if (!node) return undefined
    if (legacy) {
      node.hidden = false
      node.classList.remove('is-spa-idle')
    } else {
      node.hidden = true
      node.classList.add('is-spa-idle')
    }
    return undefined
  }, [legacy])

  return (
    <div className="od-admin-shell">
      <AdminSideRail railState={railState} onCloseDrawer={closeDrawer} />
      {drawerOpen ? (
        <button
          type="button"
          className="od-rail__scrim"
          aria-label="Close navigation"
          onClick={closeDrawer}
        />
      ) : null}
      <AdminTopNav onToggleRail={toggleRail} railState={railState} />
      <SectionTopNav />
      {/* Legacy Jinja pages (resolveRenderMode() === 'legacy') render chrome
          only — no <main>, no <Routes>. The one intentional Jinja-DOM sniff
          lives in hasLegacyBody() above. */}
      {!legacy ? (
        <main className="od-admin-main">
          <AdminRoutes />
        </main>
      ) : null}
    </div>
  )
}
