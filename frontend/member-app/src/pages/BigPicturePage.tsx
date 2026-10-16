import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchBrowseGames } from '../api/browse'
import { initiateGameDownload } from '../api/downloads'
import { queueClientCommand } from '../api/clientCommands'
import { VoiceLobby } from '../components/VoiceLobby'
import { SocialCompanionDock } from '../components/SocialCompanionDock'
import { PageStatus } from '../components/PageStatus'
import { coverUrl } from '../utils/coverUrl'
import { showToast } from '../utils/toast'
import { isThinSeat } from '../utils/seatMode'
import './BigPicturePage.css'
import { useShellConfig } from '@oneirodex/ui'

const DEFAULT_PER_PAGE = 48
const GAMEPAD_DEADZONE = 0.5
const GAMEPAD_REPEAT_MS = 220

function badgeBits(game: any) {
  const bits = []
  if (game.owned || game.store_owned) {
    bits.push('OWNED')
  }
  if (
    game.lifecycle_state === 'update_available' ||
    game.freshness_status === 'behind' ||
    game.freshness_status === 'heuristic_behind'
  ) {
    bits.push('UPDATE')
  }
  if (game.needs_translation) {
    bits.push('LANG')
  }
  if (game.has_translation_patch) {
    bits.push('PATCH')
  }
  if (game.client_connected) {
    bits.push('CLIENT')
  }
  return bits
}

function gameDetailsUrl(uuid: any) {
  return `/game_details/${encodeURIComponent(uuid)}`
}

/**
 * TC-3 honesty on the ten-foot screen.
 *
 * Big Picture offered Download and Install with no seat check, while
 * `GameActionBar` has refused both on a thin seat since TC-3 shipped. A thin
 * token is denied `write:download` server-side and the thin build carries no
 * install ACL, so the button could never complete — it just failed further
 * from the press, which on a TV with a gamepad is the worst place to find out.
 *
 * Say it once, in the place the press would have happened.
 */
function refuseOnThinSeat() {
  if (!isThinSeat()) return false
  showToast(
    'Browse & social seat — downloads and installs happen on the desktop companion.',
    'info',
  )
  return true
}

function attractUrl(uuid: any) {
  const qs = new URLSearchParams({ attract_mode: 'true' })
  if (uuid) {
    qs.set('game', uuid)
  }
  return `/trailers?${qs.toString()}`
}

function focusGameFromQuery() {
  try {
    return new URLSearchParams(window.location.search).get('game') || ''
  } catch (_err: any) {
    return ''
  }
}

export function BigPicturePage() {
  const navigate = useNavigate()
  const shellConfig = useShellConfig()
  const perPage = Number(shellConfig.perPage) || DEFAULT_PER_PAGE
  // Latched once per render rather than per press: the seat cannot change
  // while this page is mounted.
  const thinSeat = isThinSeat()
  const [games, setGames] = useState<any>(null)
  const [error, setError] = useState<any>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [index, setIndex] = useState(0)
  // Default closed so /api/activity/stream is not held open on enter (SSE gate).
  const [socialOpen, setSocialOpen] = useState(false)
  const tileRefs = useRef<any[]>([])
  const autoFocused = useRef(false)
  const padState = useRef<{
    games: LooseProps[]
    index: number
    select: (nextIndex: number) => void
    download: (uuid: string) => void
  }>({ games: [], index: 0, select: () => {}, download: () => {} })

  const requestDownload = async (uuid: string) => {
    try {
      await initiateGameDownload(uuid)
      navigate('/downloads')
    } catch (error: unknown) {
      showToast(error instanceof Error ? error.message : 'Unable to start this download.', 'error')
    }
  }
  padState.current.download = requestDownload

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setError(null)
    setGames(null)

    fetchBrowseGames(
      { per_page: perPage, sort_by: 'date_identified', sort_order: 'desc' },
      { signal: controller.signal },
    )
      .then((data) => {
        if (!active) {
          return
        }
        const list = Array.isArray(data.games) ? data.games : []
        const wanted = focusGameFromQuery()
        const found = wanted ? list.findIndex((game: any) => game.uuid === wanted) : -1
        tileRefs.current = []
        setGames(list)
        setIndex(found >= 0 ? found : 0)
      })
      .catch((err: any) => {
        if (active && err.name !== 'AbortError') {
          setError(err)
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [perPage, retryCount])

  const list = games || []
  const selected = list[index] || null
  const loading = !error && games === null

  const select = (nextIndex: any) => {
    if (!list.length) {
      return
    }
    const clamped = Math.max(0, Math.min(list.length - 1, nextIndex))
    setIndex(clamped)
    const tile = tileRefs.current[clamped]
    tile?.focus()
    tile?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest', inline: 'center' })
  }

  useEffect(() => {
    padState.current = { games: list, index, select, download: requestDownload }
  })

  useEffect(() => {
    if (autoFocused.current || !games || games.length === 0) {
      return
    }
    autoFocused.current = true
    tileRefs.current[index]?.focus()
  }, [games, index])

  useEffect(() => {
    if (typeof navigator === 'undefined' || typeof navigator.getGamepads !== 'function') {
      return undefined
    }

    let frame = 0
    let axisLatch = 0
    let lastNav = 0
    let confirmLatch = false

    const poll = () => {
      const pad = (navigator.getGamepads() || [])[0]
      const { games: padGames, index: padIndex } = padState.current
      if (!pad || !padGames.length) {
        frame = requestAnimationFrame(poll)
        return
      }

      const now = performance.now()
      const axisX = pad.axes[0] || 0
      const dpadLeft = pad.buttons[14]?.pressed
      const dpadRight = pad.buttons[15]?.pressed
      const dpadUp = pad.buttons[12]?.pressed
      const dpadDown = pad.buttons[13]?.pressed
      const confirm = pad.buttons[0]?.pressed
      const west = pad.buttons[2]?.pressed
      const east = pad.buttons[1]?.pressed

      let dir = 0
      if (axisX <= -GAMEPAD_DEADZONE || dpadLeft || dpadUp) {
        dir = -1
      } else if (axisX >= GAMEPAD_DEADZONE || dpadRight || dpadDown) {
        dir = 1
      }

      if (dir !== 0 && (dir !== axisLatch || now - lastNav > GAMEPAD_REPEAT_MS)) {
        padState.current.select(padIndex + dir)
        axisLatch = dir
        lastNav = now
      } else if (dir === 0) {
        axisLatch = 0
      }

      if (confirm) {
        if (!confirmLatch && now - lastNav > GAMEPAD_REPEAT_MS) {
          window.location.href = gameDetailsUrl(padGames[padIndex].uuid)
          lastNav = now
        }
        confirmLatch = true
      } else {
        confirmLatch = false
      }

      if (west && now - lastNav > GAMEPAD_REPEAT_MS) {
        if (!refuseOnThinSeat()) {
          padState.current.download(padGames[padIndex].uuid)
        }
        lastNav = now
      }

      if (east && now - lastNav > GAMEPAD_REPEAT_MS) {
        window.location.href = attractUrl(padGames[padIndex].uuid)
        lastNav = now
      }

      frame = requestAnimationFrame(poll)
    }

    frame = requestAnimationFrame(poll)
    return () => cancelAnimationFrame(frame)
  }, [])

  const onKeyDown = (event: any) => {
    if (event.key === 'b' || event.key === 'B') {
      event.preventDefault()
      window.location.href = attractUrl(selected?.uuid)
      return
    }

    if (!list.length) {
      return
    }

    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        event.preventDefault()
        select(index + 1)
        break
      case 'ArrowLeft':
      case 'ArrowUp':
        event.preventDefault()
        select(index - 1)
        break
      case 'Home':
        event.preventDefault()
        select(0)
        break
      case 'End':
        event.preventDefault()
        select(list.length - 1)
        break
      case 'd':
      case 'D':
        event.preventDefault()
        if (!refuseOnThinSeat()) {
          void requestDownload(list[index].uuid)
        }
        break
      case 'Escape':
        event.preventDefault()
        tileRefs.current[index]?.blur()
        break
      default:
        break
    }
  }

  let heroTitle = 'No games'
  if (loading) {
    heroTitle = 'Loading…'
  } else if (selected) {
    heroTitle = selected.name || 'Untitled'
  }

  const heroMeta = selected
    ? [badgeBits(selected).join(' · '), selected.size ? String(selected.size) : '']
        .filter(Boolean)
        .join(' · ')
    : ''

  return (
    <div className={`od-bp${shellConfig.role === 'child' ? ' od-bp--kid' : ''}`}>
      <header className="od-bp__header">
        <div>
          <h1 className="od-bp__title">Big Picture</h1>
          <p className="od-bp__hint">
            {shellConfig.role === 'child'
              ? 'Kid mode — library already filtered by parental ACL · ← → browse · Esc exit · Y friends'
              : '← → browse · Enter / A open · D download · B attract · Y friends · Esc blur · Home first'}
          </p>
        </div>
        <div className="od-bp__header-actions">
          <button
            type="button"
            className="od-bp__link"
            aria-pressed={socialOpen}
            title="Toggle friends companion (Y)"
            onClick={() => setSocialOpen((value) => !value)}
          >
            Friends
          </button>
          <a
            className="od-bp__link"
            href={attractUrl(selected?.uuid)}
            title="Open Attract Mode (B)"
          >
            Attract
          </a>
          <a className="od-bp__exit" href="/library">
            Exit
          </a>
        </div>
      </header>

      {error ? (
        <PageStatus
          error={error}
          errorMessage="Unable to load Big Picture."
          onRetry={() => setRetryCount((n) => n + 1)}
          retryLabel="Retry"
          className="od-bp__alert"
        />
      ) : null}

      {!error ? (
        <section className="od-bp__hero" aria-live="polite">
          {selected?.cover_url ? (
            <img className="od-bp__hero-art" src={coverUrl(selected.cover_url)} alt="" />
          ) : null}
          <div className="od-bp__hero-body">
            <h2 className="od-bp__hero-title">{heroTitle}</h2>
            {heroMeta ? <p className="od-bp__hero-meta">{heroMeta}</p> : null}
            {selected?.summary ? (
              <p className="od-bp__hero-summary">{String(selected.summary).slice(0, 280)}</p>
            ) : null}
            {selected ? (
              <div className="od-bp__hero-actions">
                <Link className="od-bp__btn od-bp__btn--primary" to={gameDetailsUrl(selected.uuid)}>
                  Open
                </Link>
                {thinSeat ? null : (
                  <button
                    type="button"
                    className="od-bp__btn"
                    onClick={() => void requestDownload(selected.uuid)}
                  >
                    Download
                  </button>
                )}
                {!thinSeat &&
                selected.client_connected &&
                selected.lifecycle_state === 'downloaded' ? (
                  <button
                    type="button"
                    className="od-bp__btn"
                    onClick={() => {
                      void queueClientCommand(selected.uuid, 'install').then(() => {
                        showToast('Install queued for companion', 'success')
                      })
                    }}
                  >
                    Install
                  </button>
                ) : null}
                <Link className="od-bp__btn" to="/library">
                  Exit
                </Link>
              </div>
            ) : null}
            {selected?.uuid ? <VoiceLobby gameUuid={selected.uuid} compact /> : null}
          </div>
        </section>
      ) : null}

      {!error ? (
        <div className="od-bp__rail-wrap">
          {loading ? (
            <PageStatus loading loadingMessage="Loading games…" className="od-bp__empty" />
          ) : null}

          {!loading && list.length === 0 ? (
            <PageStatus emptyMessage="No games in your library yet." className="od-bp__empty" />
          ) : null}

          {!loading && list.length > 0 ? (
            <div
              className="od-bp__rail"
              role="listbox"
              aria-label="Game rail"
              onKeyDown={onKeyDown}
            >
              {list.map((game: any, i: any) => (
                <a
                  key={game.uuid}
                  ref={(element) => {
                    tileRefs.current[i] = element
                  }}
                  className={`od-bp__tile${i === index ? ' od-bp__tile--focused' : ''}`}
                  role="option"
                  aria-label={game.name || 'Untitled'}
                  aria-selected={i === index}
                  tabIndex={i === index ? 0 : -1}
                  href={gameDetailsUrl(game.uuid)}
                  data-index={i}
                  onFocus={() => setIndex(i)}
                >
                  <img
                    className="od-bp__tile-art"
                    src={coverUrl(game.cover_url)}
                    alt=""
                    width={220}
                    height={293}
                    loading="lazy"
                    decoding="async"
                  />
                  <span className="od-bp__tile-badges">
                    {badgeBits(game).map((bit) => (
                      <span key={bit} className="od-bp__badge">
                        {bit}
                      </span>
                    ))}
                  </span>
                  <span className="od-bp__tile-label">{game.name || 'Untitled'}</span>
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <SocialCompanionDock
        mode="big-picture"
        gameUuid={selected?.uuid || ''}
        open={socialOpen}
        onOpenChange={setSocialOpen}
      />
    </div>
  )
}
