import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchLibraryPlatforms } from '../api/systems'
import { familyForPlatform } from '../chrome/platformSkins'
import { roomIdForPlatform, roomStyle } from '../chrome/playRooms'
import { isNativePcPlatform } from '../chrome/regions'
import { PageStatus } from '../components/PageStatus'
import { SystemGlyph } from '../components/systemMotifArt'
import './SystemsPage.css'

const COLLAPSED_FAMILIES_KEY = 'od.systems.collapsedFamilies'

/**
 * Which manufacturer sections the member has folded on Systems.
 * Persisted so a long page stays manageable across visits.
 */
function useCollapsedFamilies() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      const raw = window.localStorage.getItem(COLLAPSED_FAMILIES_KEY)
      return new Set(raw ? JSON.parse(raw) : [])
    } catch {
      return new Set()
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_FAMILIES_KEY, JSON.stringify([...collapsed]))
    } catch {
      // Preference only.
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

function activeThemeSlug() {
  if (typeof document === 'undefined') return 'default'
  return document.documentElement.getAttribute('data-theme') || 'default'
}

/** AI mark when present for the active theme; otherwise the SVG motif. */
function SystemMark({ platformValue, family }: LooseProps) {
  const platformId = String(platformValue || '').toLowerCase()
  const theme = activeThemeSlug()
  const [failed, setFailed] = useState(false)
  const src = platformId
    ? `/static/library/system-marks/${encodeURIComponent(theme)}/${encodeURIComponent(platformId)}.webp`
    : null

  if (!src || failed) {
    return <SystemGlyph platformValue={platformValue} family={family} />
  }

  return (
    <img
      className="od-systems-tile__mark-img"
      src={src}
      alt=""
      width={88}
      height={88}
      decoding="async"
      onError={() => setFailed(true)}
    />
  )
}

const FAMILY_ORDER = ['nintendo', 'sony', 'xbox', 'sega', 'pc', 'atari']

const FAMILY_LABELS: Record<string, string> = {
  nintendo: 'Nintendo',
  sony: 'Sony',
  xbox: 'Xbox',
  sega: 'Sega',
  pc: 'PC & Other',
  atari: 'Retro & Classic',
}

function playModeLabel(mode: any) {
  if (mode === 'browser') {
    return 'Browser'
  }
  if (mode === 'companion') {
    return 'Companion'
  }
  if (mode === 'catalog') {
    return 'Catalog'
  }
  return null
}

function groupPlatforms(platforms: any) {
  const groups = new Map()
  for (const platform of platforms) {
    const family = familyForPlatform(platform.value || platform.id)
    if (!groups.has(family)) {
      groups.set(family, [])
    }
    groups.get(family).push(platform)
  }
  return FAMILY_ORDER.filter((id) => groups.has(id)).map((id) => ({
    id,
    label: FAMILY_LABELS[id] || id,
    platforms: groups.get(id),
  }))
}

export function SystemsPage() {
  const [platforms, setPlatforms] = useState<any>(null)
  const [error, setError] = useState<any>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [collapsedFamilies, toggleFamily] = useCollapsedFamilies()

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setError(null)

    fetchLibraryPlatforms({ signal: controller.signal })
      .then((data) => {
        if (active) {
          setPlatforms(Array.isArray(data) ? data : [])
        }
      })
      .catch((err: any) => {
        if (active && err.name !== 'AbortError') {
          setError(err)
          // Keep platforms null so the error/retry UI wins over empty-state.
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [retryCount])

  const groups = useMemo(() => groupPlatforms(platforms || []), [platforms])

  if (error && !platforms) {
    return (
      <div className="od-more-page od-systems-page">
        <PageStatus
          error={error}
          errorMessage="Unable to load systems."
          onRetry={() => setRetryCount((n) => n + 1)}
          retryLabel="Retry"
        />
      </div>
    )
  }

  if (platforms === null) {
    return (
      <div className="od-more-page od-systems-page">
        <PageStatus loading loadingMessage="Loading systems…" />
      </div>
    )
  }

  if (platforms.length === 0) {
    return (
      <div className="od-more-page od-systems-page">
        <PageStatus emptyMessage="No library platforms yet. Add a library with a console or PC platform to see it here.">
          <Link className="od-btn" to="/library">
            Browse all library
          </Link>
        </PageStatus>
        <ExportPacksSection />
      </div>
    )
  }

  return (
    <div className="od-more-page od-systems-page">
      {/* Lede and Export packs share one band at the top of the page.
          Exports used to close the page, under every console family, behind a
          rule — so it was a full-width block a member had to scroll past the
          whole library to find, and the space beside the three-line lede sat
          empty on every visit. It is a sidebar note, not a chapter: it goes
          where the unused width already was. */}
      <div className="od-systems-page__intro">
        <p className="od-more-page__lede od-systems-page__lede">
          Browse your library by console or PC. Open a system to filter the grid and apply that
          era&apos;s chrome. <Link to="/ways-to-play">Ways to Play</Link> lists Browser / Companion
          / Catalog across the catalog. Console tiles also open a licensed catalog of IGDB regional
          releases.
        </p>
        <ExportPacksSection />
      </div>
      {groups.map((group) => {
        const folded = collapsedFamilies.has(group.id)
        return (
          <section key={group.id} className="od-systems-group" data-family={group.id}>
            <h2 className="od-systems-group__title">
              <button
                type="button"
                className="od-systems-group__toggle"
                aria-expanded={!folded}
                onClick={() => toggleFamily(group.id)}
              >
                <span className="od-systems-group__caret" aria-hidden="true" />
                <span>{group.label}</span>
              </button>
            </h2>
            {folded ? null : (
              <div className="od-systems-grid">
                {group.platforms.map((platform: any) => {
                  const value = platform.value || platform.id
                  const count = Number(platform.game_count) || 0
                  const modeLabel = playModeLabel(platform.play_mode)
                  const completion = platform.set_completion
                  return (
                    <div
                      key={value}
                      className="od-systems-tile od-btn"
                      data-platform={value}
                      data-family={group.id}
                      data-play-mode={platform.play_mode || undefined}
                      /* FEAT-D5: dressed for the room it was played in, not the
                         brand that made it. */
                      data-room={roomIdForPlatform(value)}
                      style={roomStyle(value)}
                    >
                      <Link
                        className="od-systems-tile__main"
                        to={`/library?library_platform=${encodeURIComponent(value)}`}
                      >
                        {/* Prefer a themed AI mark when generated; else SystemGlyph. */}
                        <span className="od-systems-tile__mark" aria-hidden="true">
                          <SystemMark platformValue={value} family={group.id} />
                        </span>
                        <span className="od-systems-tile__body">
                          <span className="od-systems-tile__name">{platform.name || value}</span>
                          <span className="od-systems-tile__count">
                            {count} {count === 1 ? 'game' : 'games'}
                            {modeLabel ? (
                              <span
                                className={`od-systems-tile__mode od-systems-tile__mode--${platform.play_mode}`}
                              >
                                {modeLabel}
                              </span>
                            ) : null}
                          </span>
                          {completion ? (
                            <span className="od-systems-tile__completion">
                              {completion.owned} / {completion.total} · {completion.percent}% (
                              {completion.region})
                            </span>
                          ) : null}
                          {Array.isArray(platform.set_completion_regions) &&
                          platform.set_completion_regions.length > 1 ? (
                            <span
                              className="od-systems-tile__regions"
                              aria-label="Set completion by region"
                            >
                              {platform.set_completion_regions.map((regionRow: any) => {
                                const pct = Number(regionRow.percent) || 0
                                const heat =
                                  pct >= 90 ? 'high' : pct >= 50 ? 'mid' : pct > 0 ? 'low' : 'empty'
                                return (
                                  <Link
                                    key={regionRow.region}
                                    className={`od-systems-tile__region od-systems-tile__region--${heat}`}
                                    to={`/systems/completion?library_platform=${encodeURIComponent(value)}&region=${encodeURIComponent(regionRow.region)}`}
                                    title={`${regionRow.region}: ${regionRow.owned}/${regionRow.total} (${regionRow.percent}%)`}
                                  >
                                    {regionRow.region}
                                    <span className="od-systems-tile__region-pct">
                                      {regionRow.percent}%
                                    </span>
                                  </Link>
                                )
                              })}
                            </span>
                          ) : null}
                        </span>
                      </Link>
                      {!isNativePcPlatform(value) || completion ? (
                        <div className="od-systems-tile__links">
                          {isNativePcPlatform(value) ? null : (
                            <Link
                              className="od-systems-tile__set-link"
                              to={`/systems/catalog?library_platform=${encodeURIComponent(value)}`}
                            >
                              Catalog
                            </Link>
                          )}
                          {completion ? (
                            <Link
                              className="od-systems-tile__set-link"
                              to={`/systems/completion?library_platform=${encodeURIComponent(value)}&region=${encodeURIComponent(completion.region)}`}
                            >
                              Missing
                            </Link>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}

function ExportPacksSection() {
  return (
    <section className="od-systems-exports" aria-labelledby="od-systems-exports-title">
      <h2 id="od-systems-exports-title" className="od-systems-group__title">
        Export packs
      </h2>
      {/* Buttons lead, prose follows. In a narrow column the two downloads are
          the only actionable part; the paragraph explaining what the files are
          is small print you read once.

          Pills, not boxes — same call as Open path on Game details. These are
          optional exports for other frontends, and a boxed button reads with
          the same weight as the console tiles below it, which are the reason
          anyone is on this page. A pill says "secondary, take it or leave it"
          without shrinking the target. */}
      <div className="od-systems-exports__actions">
        <a className="od-btn od-btn--sm od-btn--pill" href="/api/export/esde">
          ES-DE gamelist.xml
        </a>
        <a className="od-btn od-btn--sm od-btn--pill" href="/api/export/pegasus?platform=Library">
          Pegasus metadata
        </a>
      </div>
      <p className="od-systems-exports__lede">
        Optional downloads for other frontends — not required to browse here. <strong>ES-DE</strong>{' '}
        gets a <code>gamelist.xml</code> (EmulationStation Desktop Edition style list).{' '}
        <strong>Pegasus</strong> gets a metadata pack for its frontend. File paths stay portable
        under your library roots so home/NAS mounts are not leaked.
      </p>
    </section>
  )
}
