/** Play and status entries the row layout adds to the card's overflow menu. */
export function GameCardRowActions({
  playHref,
  resuming,
  playBlocked,
  showPlayStatus,
  closeMenu,
  onExplainBlock,
  onChangeStatus,
}: {
  playHref: string | null | undefined
  resuming: boolean
  playBlocked: boolean
  showPlayStatus: boolean
  closeMenu: () => void
  onExplainBlock: () => void
  onChangeStatus: () => void
}) {
  const fromMenu = (open: () => void) => () => {
    closeMenu()
    open()
  }
  return (
    <>
      {playHref ? (
        <a className="menu-button" href={playHref}>
          {resuming ? 'Resume in browser' : 'Play in browser'}
        </a>
      ) : (
        playBlocked && (
          <button type="button" className="menu-button" onClick={fromMenu(onExplainBlock)}>
            Why is play unavailable?
          </button>
        )
      )}
      {showPlayStatus && (
        <button type="button" className="menu-button" onClick={fromMenu(onChangeStatus)}>
          Change play status
        </button>
      )}
    </>
  )
}

/** Hint and short label for the first reason browser play is blocked. */
export function playBlockCopy(
  fileMissing: boolean,
  firmwareBlocked: boolean,
  hints: { file: string; firmware: string; archive: string },
) {
  if (fileMissing) return { hint: hints.file, label: 'game file missing' }
  if (firmwareBlocked) return { hint: hints.firmware, label: 'firmware missing' }
  return { hint: hints.archive, label: 'unsupported archive' }
}

function releaseYear(value: unknown) {
  if (!value) return ''
  const match = String(value).match(/^(\d{4})/)
  return match ? match[1] : ''
}

/** Title, year/genres, platform and play status for the row layout. */
export function GameCardRowMeta({
  game,
  platform,
  status,
}: {
  game: {
    uuid: string
    name: string
    first_release_date?: unknown
    genres?: string[] | null
    library_platform?: string | null
    library_platform_label?: string | null
  }
  platform: { full?: string; extra?: number } | null | undefined
  status: string | null
}) {
  return (
    <a className="game-card__row-meta" href={`/game_details/${game.uuid}`}>
      <span className="game-card__row-identity">
        <strong className="game-card__row-title">{game.name}</strong>
        <span className="game-card__row-detail">
          {[releaseYear(game.first_release_date), game.genres?.slice(0, 2).join(' / ')]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </span>
      <span className="game-card__row-platform">
        {platform?.full ||
          game.library_platform_label ||
          game.library_platform ||
          'Platform unknown'}
        {platform?.extra ? ` +${platform.extra}` : ''}
      </span>
      {status && <span className="game-card__row-status">{status}</span>}
    </a>
  )
}
