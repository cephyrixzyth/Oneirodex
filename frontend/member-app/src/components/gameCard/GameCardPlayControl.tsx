import type { CardGame } from './cardTypes'
import { formatRelativeTime } from '../../utils/formatRelativeTime'
import { FIRMWARE_ADMIN_HREF, FIRMWARE_HELP_HREF } from '../../utils/playHonesty'
import { Link } from 'react-router-dom'

/** Play / Resume in the browser, or the honest reason it cannot. */
export function GameCardPlayControl({
  firmwareBlocked,
  game,
  isAdmin,
  playBlockHint,
  playBlockLabel,
  playBlocked,
  playHref,
  playInfoOpen,
  resumeState,
  setMenuOpen,
  setPlayInfoOpen,
  setStatusOpen,
}: {
  firmwareBlocked: boolean
  game: CardGame
  isAdmin: boolean
  playBlockHint: string | null
  playBlockLabel: string
  playBlocked: boolean
  playHref: string | null
  playInfoOpen: boolean
  resumeState: CardGame['resume_state']
  setMenuOpen: (open: boolean) => void
  setPlayInfoOpen: (update: boolean | ((open: boolean) => boolean)) => void
  setStatusOpen: (open: boolean) => void
}) {
  return (
    <>
      {playHref ? (
        <a
          className={resumeState ? 'od-tile-play od-tile-play--resume' : 'od-tile-play'}
          href={playHref}
          title={
            resumeState
              ? `Resume where you left off (${formatRelativeTime(resumeState.updated_at)})`
              : 'Play in browser'
          }
          aria-label={
            resumeState ? `Resume ${game.name} in browser` : `Play ${game.name} in browser`
          }
          onClick={(event) => event.stopPropagation()}
        >
          {resumeState ? 'Resume' : 'Play'}
        </a>
      ) : playBlocked ? (
        <>
          {/* A button, not a dead <span>. The blocker copy used to live in a
              native `title`: invisible on touch, unreachable by keyboard, and
              gone the moment the pointer moved. Play is exactly the control a
              member presses when they do not know why something will not run,
              so it has to be able to answer. */}
          <button
            type="button"
            className="od-tile-play od-tile-play--disabled"
            aria-expanded={playInfoOpen}
            aria-controls={playInfoOpen ? `playBlock-${game.uuid}` : undefined}
            aria-label={`${game.name}: browser play unavailable — ${playBlockLabel}. Why?`}
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              setMenuOpen(false)
              setStatusOpen(false)
              setPlayInfoOpen((open) => !open)
            }}
            onPointerDown={(event) => event.stopPropagation()}
          >
            {game.play_blocker === 'missing_game_file' ? 'File needed' : 'Play'}
          </button>
          {playInfoOpen && (
            <div
              id={`playBlock-${game.uuid}`}
              className="popup-menu popup-menu--play"
              role="dialog"
              aria-label={`Why ${game.name} cannot be played in the browser`}
            >
              <p className="popup-menu__note">{playBlockHint}</p>
              {firmwareBlocked && isAdmin ? (
                <div className="menu-item">
                  <a className="menu-button" href={FIRMWARE_ADMIN_HREF}>
                    Emulator profiles
                  </a>
                </div>
              ) : null}
              <div className="menu-item">
                <Link
                  className="menu-button"
                  to={FIRMWARE_HELP_HREF}
                  onClick={() => setPlayInfoOpen(false)}
                >
                  Browser play requirements
                </Link>
              </div>
              <div className="menu-item">
                <Link
                  className="menu-button"
                  to={`/report?${new URLSearchParams({
                    area: 'library',
                    title: `Cannot play ${game.name} in browser (${playBlockLabel})`,
                    url: `/game_details/${game.uuid}`,
                  })}`}
                  onClick={() => setPlayInfoOpen(false)}
                >
                  Report an issue
                </Link>
              </div>
            </div>
          )}
        </>
      ) : null}
    </>
  )
}
