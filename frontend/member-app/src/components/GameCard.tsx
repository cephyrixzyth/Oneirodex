import { useEffect, useRef, useState } from 'react'
import { statusConfig } from './gameCard/playStatus'
import { GameCardAdminMenu } from './gameCard/GameCardAdminMenu'
import { GameCardPlayControl } from './gameCard/GameCardPlayControl'
import { GameCardStatusControl } from './gameCard/GameCardStatusControl'
import { setGameStatus, toggleFavorite } from '../api/userActions'
import { coverUrl, DEFAULT_COVER_URL } from '../utils/coverUrl'
import { CoverFallback } from './CoverFallback'
import { safeHttpUrl } from '../utils/safeUrl'
import { resumeHref } from '../api/saves'
import { editionChipLabels } from '../utils/platformAbbrev'
import { trailerEmbedUrls, prefersReducedMotion } from '../utils/detailsMedia'
import { BadgeStack } from './BadgeStack'
import { GamePreviewPopup } from './GamePreviewPopup'
import { HOVER_TRAILER_MS, TileHoverTrailer } from './TileHoverTrailer'
import { firmwareBlockMessage, isFirmwarePlayBlocked } from '../utils/playHonesty'

const DEFAULT_COVER = DEFAULT_COVER_URL

// `color` is a `var(--od-status-*)` reference — canonical values live in
// oneirodex/setup/default_theme/css/od-tokens.css. It is written into
// `style={{ background: currentStatus.color }}` on the status dot, so the token
// resolves at the use site.
const LONG_PRESS_MS = 480

/**
 * Fired when a tile opens a menu, so every other tile closes its own.
 *
 * The document-level click handler below cannot do this on its own: opening a
 * second menu means clicking that card's hamburger, and that handler calls
 * `stopPropagation()` so the click never reaches document — so the first menu
 * stayed open and two lived on screen at once. Same singleton pattern
 * GamePreviewPopup already uses for previews, and for the same reason: the
 * alternative is lifting menu state into the grid, which would re-render every
 * tile whenever any one of them opened a menu.
 */
const TILE_OVERLAY_OPENED = 'od-tile-overlay-opened'

function releaseYear(value: any) {
  if (!value) return ''
  const match = String(value).match(/^(\d{4})/)
  return match ? match[1] : ''
}

export function GameCard({
  game,
  showPlayStatus = false,
  isAdmin = false,
  enableDeleteOnDisk = false,
  onToggleFavorite,
  hidePlatformChip = false,
  selectionEnabled = false,
  selected = false,
  onSelectionToggle,
  // The system filter in force, when there is one. The chip names the system
  // you are looking at rather than the newest one the title exists on — see
  // editionChipLabels.
  activePlatform = '',
  layout = 'tile',
  discoverReason = '',
}: LooseProps) {
  const cardRef = useRef<any>(null)
  const menuButtonRef = useRef<HTMLButtonElement | null>(null)
  const longPressTimer = useRef(0)
  const longPressFired = useRef(false)
  const trailerTimer = useRef(0)
  const [isFavorite, setIsFavorite] = useState(Boolean(game.is_favorite))
  const [favoritePending, setFavoritePending] = useState(false)
  // Where the press began — see the click handler on .game-card for why the
  // click target itself cannot be trusted here.
  const pressStartedOnControl = useRef(false)
  // The cover <a> is the navigation, so the recovery click just fires it.
  //
  // This used useNavigate(), which made a Router a hard requirement for every
  // GameCard. GameCard.test.jsx renders bare on purpose — "a badge does not
  // [need a router]" — so that broke 27 tests across two suites. Clicking the
  // anchor keeps the href as the single source of truth and needs no context.
  const coverLinkRef = useRef<any>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [status, setStatus] = useState(game.user_status || '')
  const [statusPending, setStatusPending] = useState(false)
  const [statusOpen, setStatusOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  // Why a blocked Play cannot run. A native `title` was the only answer
  // before, which never appears on touch and is unreachable by keyboard —
  // so the one control that needs an explanation was the one that could not
  // give one.
  const [playInfoOpen, setPlayInfoOpen] = useState(false)
  const [imgSrc, setImgSrc] = useState(() => coverUrl(game.cover_url))
  // A cover that never arrives is drawn, not fetched — see CoverFallback.
  const [coverFailed, setCoverFailed] = useState(false)
  const [trailerArmed, setTrailerArmed] = useState(false)
  const currentStatus = statusConfig(status)
  const igdbUrl = safeHttpUrl(game.url)
  const steamAppId = game.steam_app_id ? Number(game.steam_app_id) : null
  const steamStoreUrl =
    safeHttpUrl(game.steam_url) ||
    (steamAppId ? `https://store.steampowered.com/app/${steamAppId}` : null)
  const steamRunUrl = steamAppId ? `steam://run/${steamAppId}` : null
  const firmwareBlocked = isFirmwarePlayBlocked(game)
  // Browser play, not a demo. It was `playHref`, which read as "this is
  // the demo link" and was the reason a "Play demo" item sat in the tile menu
  // for a feature that does not exist. `demo_url` stays as a fallback because
  // some rows genuinely carry one and it is still the thing PLAY should open.
  const basePlayHref = firmwareBlocked ? null : game.play_url || game.demo_url || null
  // A state on the server turns Play into Resume: same room, the shell offers
  // that slot first and still asks before loading it. `demo_url` rows never
  // carry a state, so they keep reading Play.
  const resumeState = game.resume_state && game.play_url ? game.resume_state : null
  const playHref =
    resumeState && basePlayHref ? resumeHref(basePlayHref, resumeState.slot_name) : basePlayHref
  const archiveBlocked = game.play_blocker === 'unsupported_archive'
  const archiveBlockHint =
    game.companion_hint ||
    'This archive type cannot be extracted for browser play. Use .zip / .7z / .rar / ROM.gz or a raw ROM.'
  const firmwareHint = firmwareBlockMessage(game)
  const playBlocked = firmwareBlocked || archiveBlocked
  const playBlockHint = firmwareBlocked ? firmwareHint : archiveBlockHint
  const playBlockLabel = firmwareBlocked ? 'firmware missing' : 'unsupported archive'
  const platformChip =
    !hidePlatformChip && (game.library_platform || game.edition_platforms?.length)
      ? editionChipLabels(game, activePlatform)
      : null
  // The placeholder JPG counts as "no cover": rows created before art was
  // fetched carry it as a real `cover_url`, so treating it as an image would
  // put the old baked-in logo back on the tile it was removed from.
  const hasCover = !coverFailed && Boolean(imgSrc) && imgSrc !== DEFAULT_COVER
  const trailerSrc =
    (typeof game.trailer_embed_url === 'string' && game.trailer_embed_url.trim()) ||
    trailerEmbedUrls(game)[0] ||
    null
  useEffect(() => {
    setImgSrc(coverUrl(game.cover_url))
    setCoverFailed(false)
    setIsFavorite(Boolean(game.is_favorite))
    setStatus(game.user_status || '')
    setMenuOpen(false)
    setStatusOpen(false)
    setPlayInfoOpen(false)
    setTrailerArmed(false)
    window.clearTimeout(trailerTimer.current)
  }, [game.uuid, game.cover_url, game.is_favorite, game.user_status, game.trailer_embed_url])

  useEffect(() => {
    return () => {
      window.clearTimeout(longPressTimer.current)
      window.clearTimeout(trailerTimer.current)
    }
  }, [])

  // One tile overlay at a time, across the whole grid.
  const overlayToken = useRef<any>({})
  const anyOverlayOpen = menuOpen || statusOpen || playInfoOpen

  useEffect(() => {
    if (!anyOverlayOpen) {
      return undefined
    }
    const token = overlayToken.current
    const onOther = (event: any) => {
      if (event.detail === token) return
      setMenuOpen(false)
      setStatusOpen(false)
      setPlayInfoOpen(false)
    }
    window.addEventListener(TILE_OVERLAY_OPENED, onOther)
    window.dispatchEvent(new CustomEvent(TILE_OVERLAY_OPENED, { detail: token }))
    return () => window.removeEventListener(TILE_OVERLAY_OPENED, onOther)
  }, [anyOverlayOpen])

  useEffect(() => {
    if (!menuOpen && !statusOpen && !playInfoOpen) {
      return undefined
    }
    const closeMenus = (event: any) => {
      if (!cardRef.current?.contains(event.target)) {
        setMenuOpen(false)
        setStatusOpen(false)
        setPlayInfoOpen(false)
      }
    }

    document.addEventListener('click', closeMenus)
    return () => document.removeEventListener('click', closeMenus)
  }, [menuOpen, statusOpen, playInfoOpen])

  useEffect(() => {
    if (!menuOpen) {
      return undefined
    }
    const closeMenuOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setMenuOpen(false)
      menuButtonRef.current?.focus()
    }
    document.addEventListener('keydown', closeMenuOnEscape)
    return () => document.removeEventListener('keydown', closeMenuOnEscape)
  }, [menuOpen])

  const handleFavoriteClick = async (event: any) => {
    event.preventDefault()
    event.stopPropagation()
    if (favoritePending) {
      return
    }

    setFavoritePending(true)
    try {
      const result = await toggleFavorite(game.uuid)
      setIsFavorite(Boolean(result.is_favorite))
      onToggleFavorite?.(game.uuid, Boolean(result.is_favorite))
    } finally {
      setFavoritePending(false)
    }
  }

  const handleStatusSelect = async (nextStatus: any) => {
    if (statusPending) {
      return
    }

    setStatusOpen(false)
    setStatusPending(true)
    try {
      const result = await setGameStatus(game.uuid, nextStatus)
      setStatus(result.status || '')
    } finally {
      setStatusPending(false)
    }
  }

  const clearLongPress = () => {
    window.clearTimeout(longPressTimer.current)
    longPressTimer.current = 0
  }

  const armTrailer = () => {
    if (!trailerSrc || prefersReducedMotion()) {
      return
    }
    window.clearTimeout(trailerTimer.current)
    trailerTimer.current = window.setTimeout(() => {
      setTrailerArmed(true)
    }, HOVER_TRAILER_MS)
  }

  const disarmTrailer = () => {
    window.clearTimeout(trailerTimer.current)
    trailerTimer.current = 0
    setTrailerArmed(false)
  }

  const handlePointerLeave = () => {
    clearLongPress()
    disarmTrailer()
  }

  const handleBlurCapture = (event: any) => {
    if (!event.currentTarget.contains(event.relatedTarget)) {
      disarmTrailer()
    }
  }

  const handleSelectPointerDown = (event: any) => {
    if (!selectionEnabled || !onSelectionToggle) {
      return
    }
    if (event.button != null && event.button !== 0) {
      return
    }
    const tag = event.target?.closest?.('button, a, input, select, textarea, label')
    if (tag) {
      return
    }
    longPressFired.current = false
    clearLongPress()
    longPressTimer.current = window.setTimeout(() => {
      longPressFired.current = true
      onSelectionToggle(game.uuid, { additive: true, fromLongPress: true })
    }, LONG_PRESS_MS)
  }

  const handleSelectClick = (event: any) => {
    if (!selectionEnabled || !onSelectionToggle) {
      return
    }
    if (longPressFired.current) {
      event.preventDefault()
      event.stopPropagation()
      longPressFired.current = false
      return
    }
    if (event.shiftKey) {
      event.preventDefault()
      event.stopPropagation()
      onSelectionToggle(game.uuid, { range: true, shiftKey: true })
    }
  }

  const containerClass = [
    'game-card-container',
    selectionEnabled ? 'is-selectable' : '',
    selected ? 'is-selected' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className={containerClass}
      ref={cardRef}
      data-selected={selected ? 'true' : 'false'}
      onPointerDown={handleSelectPointerDown}
      onPointerUp={clearLongPress}
      onPointerEnter={armTrailer}
      onPointerLeave={handlePointerLeave}
      onPointerCancel={handlePointerLeave}
      onFocusCapture={armTrailer}
      onBlurCapture={handleBlurCapture}
      onClickCapture={handleSelectClick}
    >
      <div
        className="game-card"
        // Raises the card above its neighbours while a menu is open.
        //
        // The stacking used to come from `:hover` alone, so the moment the
        // pointer left the tile — which it must, to reach the menu that opens
        // below it — the card dropped back to auto and the next tile in DOM
        // order painted over the menu. On touch there is no hover at all, so
        // the menu was always underneath.
        data-overlay-open={menuOpen || statusOpen || playInfoOpen ? 'true' : undefined}
        data-name={game.name}
        data-genres={(game.genres || []).join(', ')}
        // Recovers the click the cover <a> never receives.
        //
        // `.od-tile-preview-hint` is a sibling of the cover link, and on hover
        // it becomes pointer-events:auto centred over the cover — exactly where
        // people click. A press then starts on the <img> and ends on the hint,
        // so the browser dispatches `click` on their nearest common ancestor:
        // this div, which is OUTSIDE the anchor. The link never fired and
        // clicking a tile did nothing. Verified by event capture:
        //   mousedown -> .game-cover, mouseup -> .od-tile-preview-hint,
        //   click     -> .game-card
        //
        // Which element the click RESOLVES to is unreliable for the same
        // reason, so the decision is made on where the press STARTED. The
        // cover link is excluded from the control list on purpose: a press
        // beginning on the cover is exactly the case being repaired, while a
        // press beginning on Preview / favourite / status / menu / select
        // belongs to that control and must not navigate.
        // CAPTURE phase deliberately. The preview hint, the select checkbox and
        // others call stopPropagation() on pointerdown, so a bubble-phase
        // listener here never sees their press and the click below would treat
        // a Preview press as a bare-card click and navigate. Capture runs
        // before the target's own handler, so it cannot be suppressed.
        onPointerDownCapture={(event) => {
          const control = (event.target as Element | null)?.closest?.(
            'a, button, input, select, [role="button"]',
          )
          pressStartedOnControl.current =
            !!control && !control.classList.contains('game-card__cover-link')
        }}
        onClick={(event) => {
          const startedOnControl = pressStartedOnControl.current
          pressStartedOnControl.current = false
          if (startedOnControl) return
          if (event.defaultPrevented) return
          if (event.button && event.button !== 0) return
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
          coverLinkRef.current?.click()
        }}
      >
        {selectionEnabled ? (
          <input
            type="checkbox"
            className="od-tile-select"
            checked={selected}
            aria-label={`Select ${game.name}`}
            onChange={(event) => {
              onSelectionToggle?.(game.uuid, {
                additive: true,
                checked: event.target.checked,
              })
            }}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          />
        ) : null}
        {/* Top-right stack, in the order it is painted: favourite, play
            status, menu. Favourite leads because it is the only one with a
            resting state — a favourited tile keeps its heart while the rest of
            the stack stays hidden until hover — so it must not sit underneath
            two controls that are invisible at the time. Keeping the DOM in the
            same order keeps tab order walking the stack the way the eye does. */}
        <button
          type="button"
          className={`favorite-btn${isFavorite ? ' favorited' : ''}${favoritePending ? ' processing' : ''}`}
          data-game-uuid={game.uuid}
          data-is-favorite={String(isFavorite)}
          data-chrome-anchor="top-right"
          aria-label={`${isFavorite ? 'Remove' : 'Add'} ${game.name} ${isFavorite ? 'from' : 'to'} favorites`}
          aria-pressed={isFavorite}
          disabled={favoritePending}
          onClick={handleFavoriteClick}
        >
          <span aria-hidden="true">{isFavorite ? '♥' : '♡'}</span>
        </button>

        <GameCardStatusControl
          currentStatus={currentStatus}
          game={game}
          handleStatusSelect={handleStatusSelect}
          setMenuOpen={setMenuOpen}
          setStatusOpen={setStatusOpen}
          showPlayStatus={showPlayStatus}
          status={status}
          statusOpen={statusOpen}
          statusPending={statusPending}
        />

        <button
          ref={menuButtonRef}
          id={`menuButton-${game.uuid}`}
          type="button"
          className="button-glass-hamburger"
          data-chrome-anchor="top-right"
          aria-label={`Open actions for ${game.name}`}
          aria-expanded={menuOpen}
          aria-controls={menuOpen ? `popupMenu-${game.uuid}` : undefined}
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            setStatusOpen(false)
            setMenuOpen((open) => !open)
          }}
        >
          <span aria-hidden="true">☰</span>
        </button>

        <GameCardAdminMenu
          enableDeleteOnDisk={enableDeleteOnDisk}
          game={game}
          igdbUrl={igdbUrl}
          isAdmin={isAdmin}
          menuOpen={menuOpen}
          setMenuOpen={setMenuOpen}
          steamRunUrl={steamRunUrl}
          steamStoreUrl={steamStoreUrl}
        />

        {/* The actions disclosure is followed by its native controls in Tab
            order; Preview remains the next separate tile action. */}
        <button
          type="button"
          className="od-tile-preview-hint"
          aria-label={`Preview ${game.name}`}
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            setPreviewOpen(true)
          }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          Preview
        </button>

        {/* The clip lives here now, not on .game-card — the card was clipping
            its own popup menu. See .game-card__cover-link in components.css. */}
        <a ref={coverLinkRef} className="game-card__cover-link" href={`/game_details/${game.uuid}`}>
          {/* Nothing to show is drawn, not fetched.
              The old path swapped `src` to default_cover.jpg — a raster with
              the logo and the words baked into it, unreadable below about a
              220px tile and green whatever theme was selected. The fallback
              below is CSS plus the real title, so it scales with the tile and
              follows the theme. Covers that *do* exist are unaffected. */}
          {hasCover ? (
            <img
              key={`${game.uuid}:${imgSrc}`}
              src={imgSrc}
              alt={game.name}
              className="game-cover"
              width={250}
              height={333}
              loading="lazy"
              decoding="async"
              onError={(event) => {
                const image = event.currentTarget
                if (image.dataset.fallbackApplied === '1') {
                  return
                }
                image.dataset.fallbackApplied = '1'
                image.removeAttribute('srcset')
                setCoverFailed(true)
              }}
            />
          ) : (
            <CoverFallback name={game.name} />
          )}
          <TileHoverTrailer src={trailerSrc} active={trailerArmed} />
        </a>

        {/* The tile's name — visible strip when titles are on, and the
            card's screen-reader name either way.
            This replaced a separate `.visually-hidden` span. Both together put
            the name in the DOM twice, which is noise for a screen reader and
            broke every `getByText(name)` in the suite. Sized by
            `--od-tile-title-h` (0 when off) and hidden properly rather than
            just collapsed — see components.css — so turning titles off never
            costs the accessible name. Rows layout names itself below. */}
        {layout !== 'rows' ? <span className="game-card__title">{game.name}</span> : null}

        {layout === 'rows' ? (
          <a className="game-card__row-meta" href={`/game_details/${game.uuid}`}>
            <strong className="game-card__row-title">{game.name}</strong>
            <span className="game-card__row-detail">
              {[
                platformChip?.full || game.library_platform_label,
                releaseYear(game.first_release_date),
                showPlayStatus ? currentStatus.label : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </span>
          </a>
        ) : null}

        {platformChip ? (
          <span
            className="od-platform-chip"
            title={
              platformChip.extra > 0
                ? `${platformChip.full} · also on ${platformChip.extra} other ${
                    platformChip.extra === 1 ? 'system' : 'systems'
                  }`
                : platformChip.full
            }
          >
            {platformChip.abbrev}
            {platformChip.extra > 0 ? (
              <span className="od-platform-chip__more">{`+${platformChip.extra}`}</span>
            ) : null}
          </span>
        ) : null}

        <GameCardPlayControl
          firmwareBlocked={firmwareBlocked}
          game={game}
          isAdmin={isAdmin}
          playBlockHint={playBlockHint}
          playBlockLabel={playBlockLabel}
          playBlocked={playBlocked}
          playHref={playHref}
          playInfoOpen={playInfoOpen}
          resumeState={resumeState}
          setMenuOpen={setMenuOpen}
          setPlayInfoOpen={setPlayInfoOpen}
          setStatusOpen={setStatusOpen}
        />

        <BadgeStack
          game={game}
          preferredCorner="top-left"
          collidesWithTitle={Boolean(game.badge_title_collision)}
          hasPlatformChip={!hidePlatformChip && Boolean(game.library_platform)}
        />
      </div>

      {previewOpen ? (
        <GamePreviewPopup
          game={game}
          reason={discoverReason || game.discover_reason || game.reason || ''}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}
    </div>
  )
}
