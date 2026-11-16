import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { DetailsMediaStage } from '../components/DetailsMediaStage'
import { DetailsMoreFrom } from '../components/DetailsMoreFrom'
import { DetailsStoreSpecs } from '../components/DetailsStoreSpecs'
import { CheatsPanel } from '../components/CheatsPanel'
import { SavedStatesPanel } from '../components/SavedStatesPanel'
import { AchievementsPanel } from '../components/AchievementsPanel'
import { PcCheatsPanel } from '../components/PcCheatsPanel'
import { ModsPanel } from '../components/ModsPanel'
import { RelatedMediaStrip } from '../components/RelatedMediaStrip'
import { GameActionBar } from '../components/GameActionBar'
import { OpenPathModal } from '../components/OpenPathModal'
import { PageStatus } from '../components/PageStatus'
import { ScreenshotLightbox } from '../components/ScreenshotLightbox'
import {
  adminPathRows,
  detailsDiscChips,
  extrasPanelModel,
  isVersionPathMissing,
  showsRetroarchCheats,
  trailerEmbedUrls,
  youtubeDemoLink,
} from '../utils/detailsMedia'
import { formatLocaleDate } from '../utils/formatLocaleDate'
import { ITEM_KIND_LABEL, resolveItemKind } from '../utils/itemKind'
import {
  FIRMWARE_ADMIN_HREF,
  FIRMWARE_HELP_HREF,
  firmwareBlockHint,
  firmwareBlockMessage,
  isFirmwarePlayBlocked,
} from '../utils/playHonesty'
import { detailsRootCrumb, primaryGenreName, taxonomyHref } from '../utils/detailsTaxonomy'
import { TaxonomyChip } from './gameDetails/detailsHelpers'
import { DetailsCoverColumn } from './gameDetails/DetailsCoverColumn'
import { useFreshnessCheck, useGameDetails, useVersionActions } from './gameDetails/useGameDetails'
import { DetailsExtrasSection } from './gameDetails/DetailsExtrasSection'
import { DetailsFactsSection } from './gameDetails/DetailsFactsSection'
import { DetailsQuickRows } from './gameDetails/DetailsQuickRows'
import { DetailsSummarySection } from './gameDetails/DetailsSummarySection'
import { DetailsTranslationsSection } from './gameDetails/DetailsTranslationsSection'
import { DetailsVersionsSection } from './gameDetails/DetailsVersionsSection'
import { useShellConfig } from '@oneirodex/ui'
import './GameDetailsPage.css'

export function GameDetailsPage() {
  const shellConfig = useShellConfig()
  const canDownload = String(shellConfig.role || '').toLowerCase() !== 'child'
  const { gameUuid } = useParams()
  const { game, setGame, versions, setVersions, versionsLoading, error, retry, setRetryCount } =
    useGameDetails(gameUuid)
  const versionActions = useVersionActions({ game, gameUuid, setVersions })
  const {
    busyVersionKey,
    setBusyVersionKey,
    versionActionStatus,
    setVersionActionStatus,
    cleanupBusy,
    handleVersionDownload,
    handleCleanupOrphans,
  } = versionActions
  const { freshnessBusy, freshnessError, handleFreshnessCheck } = useFreshnessCheck({
    gameUuid,
    setGame,
  })
  const [selectedCore, setSelectedCore] = useState('')
  const [shotIndex, setShotIndex] = useState<any>(null)
  /* Screenshot URLs the browser could not load.
   *
   * The payload no longer lists art it cannot serve, which fixes the common
   * case. It cannot fix the other one: a remote IGDB URL that has since gone,
   * or a local file deleted after the row was written. Either renders a broken
   * image, and a gallery of broken images is worse than no gallery — so a shot
   * that fails to load leaves the list, and a section left with nothing does
   * not render at all. */
  const [brokenShots, setBrokenShots] = useState<Set<any>>(() => new Set())

  const markShotBroken = useCallback((url: any) => {
    setBrokenShots((current) => {
      if (current.has(url)) return current
      const next = new Set(current)
      next.add(url)
      return next
    })
  }, [])
  const [pathModal, setPathModal] = useState<any>(null)

  useEffect(() => {
    if (game?.emulator_core) {
      setSelectedCore(game.emulator_core)
    }
  }, [game?.emulator_core, game?.uuid])

  const videoEmbeds = useMemo(() => trailerEmbedUrls(game), [game])

  /** Screenshots that are actually renderable — see `brokenShots`. */
  const shownShots = useMemo(
    () => (game?.screenshots || []).filter((url: any) => !brokenShots.has(url)),
    [game?.screenshots, brokenShots],
  )

  const demoLink = useMemo(() => youtubeDemoLink(game), [game])
  const pathRows = useMemo(() => adminPathRows(game), [game])
  const extrasModel = useMemo(
    () => extrasPanelModel(game, versions, { loading: versionsLoading }),
    [game, versions, versionsLoading],
  )
  const discChips = useMemo(() => detailsDiscChips(game), [game])
  const baseAndUpdates = useMemo(
    () => versions.filter((row) => row.kind === 'base' || row.kind === 'update'),
    [versions],
  )
  const hasMissingVersions = useMemo(
    () => baseAndUpdates.some((row) => isVersionPathMissing(row)),
    [baseAndUpdates],
  )

  const playHref = useMemo(() => {
    if (!game?.can_play_in_browser || isFirmwarePlayBlocked(game)) {
      return null
    }
    const cores = Array.isArray(game.emulator_cores) ? game.emulator_cores : []
    const core = selectedCore || game.emulator_core || cores[0]
    // Prefer the server play_url (WebRetro or BP-1 Nostalgist NES host) and
    // only rewrite query params when the member picks another core.
    const base = game.play_url || null
    if (!core || !game.uuid) {
      return base
    }
    try {
      const url = new URL(base || '/static/vendor/webretro/webretro.html', window.location.origin)
      url.searchParams.set('guid', game.uuid)
      url.searchParams.set('core', core)
      if (game.library_platform) {
        url.searchParams.set('platform', game.library_platform)
      }
      if (showsRetroarchCheats(game)) {
        url.searchParams.set('cheat_surface', 'retroarch')
      } else {
        url.searchParams.delete('cheat_surface')
      }
      return `${url.pathname}${url.search}`
    } catch {
      return base
    }
  }, [game, selectedCore])

  const firmwareBlocked = isFirmwarePlayBlocked(game)
  const firmwareMessage = firmwareBlocked ? firmwareBlockMessage(game) : null
  const firmwareHint = firmwareBlocked ? firmwareBlockHint(game) : null

  if (!game) {
    return (
      <div className="od-more-page od-details-page">
        <PageStatus
          loading={!error}
          error={error}
          errorMessage="Unable to load game details."
          loadingMessage="Loading game…"
          onRetry={retry}
        />
      </div>
    )
  }

  const itemKind = resolveItemKind(game)
  const rootCrumb = detailsRootCrumb(game)
  const genreName = primaryGenreName(game)
  const hasMedia = videoEmbeds.length > 0 || shownShots.length > 0

  return (
    <div className="od-more-page od-details-page">
      {/* Wide, title-free art behind the page.
          Two rules make this work as atmosphere rather than as a picture the
          content is sitting on top of: it is never the cover (the cover carries
          the title, and the title is already on the page in readable type), and
          it is obscured on three axes at once — blurred, desaturated, and faded
          out under a gradient that reaches full opacity well before the text
          starts. Aria-hidden and `pointer-events: none` because it is a surface,
          not content: nothing here is announced and nothing here is clickable.
          Absent when a title has no wide art, which leaves the page on its flat
          surface exactly as before. */}
      {game.backdrop_url ? (
        <div className="od-details-page__backdrop" aria-hidden="true">
          <img src={game.backdrop_url} alt="" loading="lazy" />
        </div>
      ) : null}
      <nav className="od-details-page__crumbs" aria-label="Breadcrumb">
        <ol>
          <li>
            <Link to={rootCrumb.to}>{rootCrumb.label}</Link>
          </li>
          {genreName ? (
            <li>
              <Link to={taxonomyHref('genre', genreName)}>{genreName}</Link>
            </li>
          ) : null}
          <li aria-current="page">
            <span>{game.name}</span>
          </li>
        </ol>
      </nav>

      <div className="od-details-page__hero">
        <DetailsCoverColumn game={game} pathRows={pathRows} setPathModal={setPathModal} />
        <div className="od-details-page__hero-main">
          <h1>{game.name}</h1>
          <p className="od-details-page__meta-line">
            {[
              game.developer,
              game.publisher,
              game.category,
              game.first_release_date
                ? formatLocaleDate(game.first_release_date, { fallback: null })
                : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
          {game.game_modes?.length || game.player_perspectives?.length ? (
            <div className="od-details-page__features" aria-label="How this plays">
              {(game.game_modes || []).map((name: any) => (
                <TaxonomyChip key={`mode:${name}`} kind="game_mode" name={name} />
              ))}
              {(game.player_perspectives || []).map((name: any) => (
                <TaxonomyChip key={`persp:${name}`} kind="player_perspective" name={name} />
              ))}
            </div>
          ) : null}
          <div className="od-details-page__chips">
            {itemKind !== 'game' ? (
              <span
                className="chip od-chip"
                title="Library item kind - gaming software, not a main-game catalog match"
              >
                {ITEM_KIND_LABEL[itemKind]}
              </span>
            ) : null}
            {game.local_version ? (
              <span className="chip od-chip" title="Installed / library version">
                Version {game.local_version}
              </span>
            ) : null}
            {game.remote_version_summary ? (
              <span className="chip od-chip" title="Remote / store version summary">
                Remote {game.remote_version_summary}
              </span>
            ) : null}
            {game.size ? <span className="chip od-chip">{game.size}</span> : null}
            {discChips.map((chip) => (
              <span key={chip.key} className="chip od-chip" title={chip.title}>
                {chip.text}
              </span>
            ))}
            {game.status_label ? <span className="chip od-chip">{game.status_label}</span> : null}
            {game.rom_region || game.rom_languages ? (
              <span className="chip od-chip" title="ROM region / languages from filename">
                {[game.rom_region, game.rom_languages].filter(Boolean).join(' · ') || 'ROM lang'}
                {game.preferred_locale_matches === true
                  ? ` · matches ${game.preferred_game_locale || 'en-US'}`
                  : null}
                {game.preferred_locale_matches === false
                  ? ` · no ${game.preferred_game_locale || 'en-US'}`
                  : null}
                {game.has_english === false ? ' · no EN' : null}
              </span>
            ) : null}
            {game.freshness_status ? (
              <span className="chip od-chip">Freshness: {game.freshness_status}</span>
            ) : null}
            {/* Companion presence reads as status, so it belongs on the status
                row rather than floating above the action buttons. */}
            <span
              className={`chip od-chip${game.client_connected ? '' : ' od-chip--muted'}`}
              title={
                game.client_connected
                  ? 'Companion client is online'
                  : 'Companion client offline — install/update/uninstall need it'
              }
            >
              {game.client_connected ? 'Companion online' : 'Companion offline'}
            </span>
            {game.hltb_main_story != null ? (
              <span className="chip od-chip">
                HLTB main {Number(game.hltb_main_story).toFixed(1)}h
              </span>
            ) : null}
            {game.is_favorite ? <span className="chip od-chip">Favorite</span> : null}
          </div>
          <GameActionBar
            gameUuid={game.uuid}
            gameName={game.name}
            lifecycleState={game.lifecycle_state || 'not_downloaded'}
            clientConnected={Boolean(game.client_connected)}
            variant="full"
            showPresence={false}
            canDownload={canDownload}
          />
          {/* Three rows, one per question, instead of one flex-wrap blob.
              As a single wrapping row the break points moved with the content:
              a title with four store links put "Check updates & DLC" alone on
              a third line, one with two links left it hanging half-way along
              the second, and "Add to collection" sat in a gap beside Play. The
              groups answer different questions — play it · find it elsewhere ·
              go and look for changes — so each owns a row and wraps inside
              itself. Narrow panes reflow within a group rather than shuffling
              buttons between groups. */}
          <DetailsQuickRows
            game={game}
            playHref={playHref}
            selectedCore={selectedCore}
            setSelectedCore={setSelectedCore}
            firmwareBlocked={firmwareBlocked}
            firmwareMessage={firmwareMessage}
            freshnessBusy={freshnessBusy}
            handleFreshnessCheck={handleFreshnessCheck}
          />
          {firmwareBlocked ? (
            <p className="od-details-page__play-honesty" role="status">
              <span>{firmwareMessage}</span>
              {firmwareHint ? (
                <span className="od-details-page__muted"> {firmwareHint}</span>
              ) : null}{' '}
              <Link to={FIRMWARE_HELP_HREF}>Help → Browser play</Link>
              {game.is_admin ? (
                <>
                  {' '}
                  · <a href={FIRMWARE_ADMIN_HREF}>Admin → Emulators</a>
                </>
              ) : null}
            </p>
          ) : null}
          {freshnessError ? (
            <PageStatus
              error={freshnessError}
              errorMessage={`Update check failed: ${String(freshnessError.message || freshnessError)}`}
              className="od-details-page__muted"
            />
          ) : null}
        </div>
      </div>

      <div className={`od-details-page__fold${hasMedia ? ' od-details-page__fold--media' : ''}`}>
        <div className="od-details-page__content-grid">
          {game.summary ? <DetailsSummarySection summary={game.summary} /> : null}

          {/* Open path rides the section heading, not the path row.
              A full-height `.od-btn` in the row's third grid column squeezed
              the path into roughly half the panel, so a normal library path
              wrapped over six lines inside a box taller than the rest of the
              facts list — and the button's own column sat mostly empty. The
              heading line already has unused width, and the action belongs to
              the section rather than to one line of it. */}
          <DetailsFactsSection game={game} pathRows={pathRows} setPathModal={setPathModal} />
        </div>

        {hasMedia ? (
          <DetailsMediaStage
            videoEmbeds={videoEmbeds}
            shownShots={shownShots}
            onFullscreen={setShotIndex}
            onShotBroken={markShotBroken}
          />
        ) : null}
      </div>

      <div className="od-details-page__flow">
        {game.storyline ? (
          <section className="od-details-page__section">
            <h2>About</h2>
            <p className="od-details-page__about">{game.storyline}</p>
          </section>
        ) : null}

        <DetailsStoreSpecs storeSpecs={game.store_specs} />

        {game.show_translations_block ? (
          <DetailsTranslationsSection
            game={game}
            busyVersionKey={busyVersionKey}
            setBusyVersionKey={setBusyVersionKey}
            setVersionActionStatus={setVersionActionStatus}
            setRetryCount={setRetryCount}
            canDownload={canDownload}
          />
        ) : null}

        {baseAndUpdates.length > 0 ? (
          <DetailsVersionsSection
            game={game}
            baseAndUpdates={baseAndUpdates}
            hasMissingVersions={hasMissingVersions}
            busyVersionKey={busyVersionKey}
            setBusyVersionKey={setBusyVersionKey}
            versionActionStatus={versionActionStatus}
            setVersionActionStatus={setVersionActionStatus}
            cleanupBusy={cleanupBusy}
            handleCleanupOrphans={handleCleanupOrphans}
            handleVersionDownload={handleVersionDownload}
            canDownload={canDownload}
          />
        ) : null}

        {/* Phase 4 save-state layer: this member's states, each a Resume
            into the room (which asks before loading). Self-gates on playHref. */}
        <SavedStatesPanel gameUuid={game.uuid} playHref={playHref} />

        {/* R1/R2: only renders for a matched set that carries achievements. */}
        <AchievementsPanel gameUuid={game.uuid} />

        {showsRetroarchCheats(game) ? (
          <CheatsPanel gameUuid={game.uuid} playHref={playHref} cheatSurface={game.cheat_surface} />
        ) : null}

        {/* FEAT-D2 — the PC counterpart. Self-gates on cheat_surface, so the two
          panels can never both render for one title. */}
        <PcCheatsPanel
          gameUuid={game.uuid}
          cheatSurface={game.cheat_surface}
          canEdit={Boolean(game.can_edit)}
        />

        {/* MOD-3 list + INSP-36 loader + INSP-22 browse. Self-gates: hidden when
          tracking is off or there is nothing to show and nobody who could add. */}
        <ModsPanel gameUuid={game.uuid} canEdit={Boolean(game.can_edit)} />

        <DetailsExtrasSection
          game={game}
          extrasModel={extrasModel}
          busyVersionKey={busyVersionKey}
          setBusyVersionKey={setBusyVersionKey}
          setVersionActionStatus={setVersionActionStatus}
          handleVersionDownload={handleVersionDownload}
          canDownload={canDownload}
        />

        {/* Related media sits above screenshots and trailer by request — it is
          context about the game, so it reads before the gallery. Renders
          nothing when a title has none. */}
        <RelatedMediaStrip gameUuid={game.uuid} />
        <DetailsMoreFrom gameUuid={game.uuid} />

        {/* The stage carries every embedded trailer, so this is only the
          no-embed case: point at the external video instead. */}
        {videoEmbeds.length === 0 && demoLink ? (
          <section className="od-details-page__section">
            <h2>Trailers &amp; videos</h2>
            <p className="od-details-page__muted">
              No embedded trailer yet.{' '}
              <a className="od-btn" href={demoLink.href} target="_blank" rel="noreferrer">
                {demoLink.label}
              </a>
            </p>
          </section>
        ) : null}
      </div>

      <ScreenshotLightbox
        urls={shownShots}
        openIndex={shotIndex}
        onClose={() => setShotIndex(null)}
      />

      <OpenPathModal
        open={Boolean(pathModal)}
        path={pathModal?.path || ''}
        label={pathModal?.label || 'Path'}
        gameUuid={game.uuid}
        clientConnected={Boolean(game.client_connected)}
        onClose={() => setPathModal(null)}
      />
    </div>
  )
}
