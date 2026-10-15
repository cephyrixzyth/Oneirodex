import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { BadgeStack } from '../../components/BadgeStack'
import { coverUrl } from '../../utils/coverUrl'
import type { DetailsGame, PathModalRequest, PathRow } from './detailsTypes'

/** Cover art, badge stack and - for admins - the actions menu. */
export function DetailsCoverColumn({
  game,
  pathRows,
  setPathModal,
}: {
  game: DetailsGame
  pathRows: PathRow[]
  setPathModal: (request: PathModalRequest | null) => void
}) {
  const [adminMenuOpen, setAdminMenuOpen] = useState(false)
  const adminMenuRef = useRef<HTMLDivElement | null>(null)
  const adminMenuTriggerRef = useRef<HTMLButtonElement | null>(null)

  useLayoutEffect(() => {
    if (!adminMenuOpen) return
    adminMenuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
  }, [adminMenuOpen])

  useEffect(() => {
    if (!adminMenuOpen) return undefined
    function onDocClick(event: MouseEvent) {
      if (!adminMenuRef.current?.contains(event.target as Node)) {
        setAdminMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [adminMenuOpen])

  return (
    <div
      className={`od-details-page__cover-wrap${adminMenuOpen ? ' od-details-page__cover-wrap--menu-open' : ''}`}
    >
      <img className="od-details-page__cover" src={coverUrl(game.cover_url)} alt="" />
      <BadgeStack game={game} preferredCorner="top-left" maxVisible={2} />
      {game.is_admin ? (
        <div
          className="od-details-page__admin-menu"
          ref={adminMenuRef}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && adminMenuOpen) {
              event.preventDefault()
              setAdminMenuOpen(false)
              adminMenuTriggerRef.current?.focus()
              return
            }
            if (!adminMenuOpen || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
              return
            }
            const items = Array.from(
              adminMenuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
            )
            if (!items.length) return
            event.preventDefault()
            const current = items.indexOf(document.activeElement as HTMLElement)
            const next =
              event.key === 'Home'
                ? 0
                : event.key === 'End'
                  ? items.length - 1
                  : event.key === 'ArrowDown'
                    ? (current + 1) % items.length
                    : (current - 1 + items.length) % items.length
            items[next].focus()
          }}
        >
          <button
            ref={adminMenuTriggerRef}
            type="button"
            className="od-details-page__admin-menu-btn"
            data-chrome-anchor="top-right"
            aria-expanded={adminMenuOpen}
            aria-haspopup="menu"
            aria-controls={adminMenuOpen ? 'od-details-admin-menu' : undefined}
            aria-label="Admin actions"
            onClick={() => setAdminMenuOpen((open) => !open)}
          >
            <span aria-hidden="true">⋮</span>
          </button>
          {adminMenuOpen ? (
            <div
              id="od-details-admin-menu"
              className="od-details-page__admin-menu-panel"
              role="menu"
              aria-label="Admin actions"
            >
              <a
                className="od-details-page__admin-menu-item"
                role="menuitem"
                tabIndex={-1}
                href={`/game_edit/${game.uuid}`}
              >
                Edit Details
              </a>
              <a
                className="od-details-page__admin-menu-item"
                role="menuitem"
                tabIndex={-1}
                href={`/edit_game_images/${game.uuid}`}
              >
                Edit Images
              </a>
              {pathRows[0] ? (
                <button
                  type="button"
                  className="od-details-page__admin-menu-item"
                  role="menuitem"
                  tabIndex={-1}
                  onClick={() => {
                    setAdminMenuOpen(false)
                    setPathModal(pathRows[0])
                  }}
                >
                  Open path
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
