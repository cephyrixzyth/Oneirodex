import type { ReactNode } from 'react'
import type { CardGame } from './cardTypes'
import { AddToCollection } from '../AddToCollection'
import { GameActionBar } from '../GameActionBar'
import { getCsrfToken } from '@oneirodex/ui'
import { Link } from 'react-router-dom'

/** The ⋮ menu: details, edit, Steam / IGDB links, delete on disk. */
export function GameCardAdminMenu({
  enableDeleteOnDisk,
  game,
  igdbUrl,
  onRowPreview,
  compactRowActions,
  isAdmin,
  menuOpen,
  setMenuOpen,
  steamRunUrl,
  steamStoreUrl,
}: {
  enableDeleteOnDisk: boolean
  game: CardGame
  compactRowActions?: ReactNode
  onRowPreview?: () => void
  igdbUrl: string | null
  isAdmin: boolean
  menuOpen: boolean
  setMenuOpen: (open: boolean) => void
  steamRunUrl: string | null
  steamStoreUrl: string | null
}) {
  return (
    <>
      {menuOpen && (
        <div id={`popupMenu-${game.uuid}`} className="popup-menu">
          {compactRowActions && (
            <div className="menu-item game-card__row-compact-actions">{compactRowActions}</div>
          )}
          {onRowPreview && (
            <div className="menu-item game-card__row-preview-action">
              <button type="button" className="menu-button" onClick={onRowPreview}>
                Preview game
              </button>
            </div>
          )}
          <div className="menu-item menu-item--action-bar">
            <GameActionBar
              gameUuid={game.uuid}
              gameName={game.name}
              variant="compact"
              lifecycleState={game.lifecycle_state || 'not_downloaded'}
              clientConnected={Boolean(game.client_connected)}
            />
          </div>
          {/* Filing a game is a decision you make while looking at it, so the
              control belongs on the tile rather than four navigations away
              inside the shelf you want to put it on. */}
          <div className="menu-item">
            <AddToCollection
              gameUuid={game.uuid}
              gameName={game.name}
              variant="menu"
              onAdded={() => setMenuOpen(false)}
            />
          </div>
          {isAdmin && (
            <>
              <div className="menu-item">
                <a className="menu-button" href={`/game_edit/${game.uuid}`}>
                  Edit Details
                </a>
              </div>
              <div className="menu-item">
                <a className="menu-button" href={`/edit_game_images/${game.uuid}`}>
                  Edit Images
                </a>
              </div>
              <form
                action={`/refresh_game_images/${game.uuid}`}
                method="post"
                className="menu-item"
              >
                <input type="hidden" name="csrf_token" value={getCsrfToken()} />
                <button type="submit" className="menu-button refresh-game-images">
                  Refresh Images
                </button>
              </form>
              <div className="menu-item">
                <button
                  type="button"
                  className="menu-button delete-game"
                  data-game-uuid={game.uuid}
                >
                  Remove Game from DB
                </button>
              </div>
              {enableDeleteOnDisk && (
                <div className="menu-item">
                  <button
                    type="button"
                    className="menu-button trigger-delete-modal"
                    data-game-uuid={game.uuid}
                  >
                    Delete Game on disk
                  </button>
                </div>
              )}
              <div className="menu-item move-library-container">
                <button
                  type="button"
                  className="menu-button move-library"
                  data-game-uuid={game.uuid}
                >
                  Move Library
                </button>
                <div className="submenu-libraries" style={{ display: 'none' }}>
                  <div className="loading-libraries">
                    <span>Loading libraries...</span>
                  </div>
                  <div className="libraries-list" style={{ display: 'none' }} />
                </div>
              </div>
            </>
          )}
          {igdbUrl && (
            <div className="menu-item">
              <a className="menu-button" href={igdbUrl} target="_blank" rel="noreferrer">
                Open catalog page
              </a>
            </div>
          )}
          {steamStoreUrl && (
            <div className="menu-item">
              <a className="menu-button" href={steamStoreUrl} target="_blank" rel="noreferrer">
                Open in Steam store
              </a>
            </div>
          )}
          {steamRunUrl && (
            <div className="menu-item">
              <a className="menu-button" href={steamRunUrl}>
                Launch via Steam
              </a>
            </div>
          )}
          {/* Last, and always present. Everything above it depends on the
              title being right; this is what a member reaches for when it is
              not — wrong artwork, wrong match, a file that will not run. The
              report form is prefilled from here so they do not have to
              describe which game they were looking at. */}
          <div className="menu-item">
            <Link
              className="menu-button"
              to={`/report?${new URLSearchParams({
                area: 'library',
                title: `Issue with ${game.name}`,
                url: `/game_details/${game.uuid}`,
              })}`}
            >
              Report an issue
            </Link>
          </div>
        </div>
      )}
    </>
  )
}
