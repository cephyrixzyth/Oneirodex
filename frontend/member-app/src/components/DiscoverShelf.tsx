import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchDiscoverRow } from '../api/discover'
import { GameCard } from './GameCard'
import { hbarLayout, scrollLeftFromPointer } from './hbarLayout'
import { NewsCard } from './NewsCard'
import { isShelfItemFullyVisible } from './shelfItemVisibility'
import { useRowScroll } from './useRowScroll'
import './DiscoverShelf.css'

/**
 * Items a row is carrying, whichever kind it is.
 *
 * Game rows keep the `games` key they have always had; rows of anything else
 * carry `items`. The server sends one or the other rather than both, because
 * mirroring the list would serialize every tile twice.
 */
export function rowItems(section: any) {
  if (Array.isArray(section?.games)) return section.games
  if (Array.isArray(section?.items)) return section.items
  return []
}

/** Stable key for a tile of any kind. Games have uuids, articles have ids. */
function itemKey(item: any, index = 0) {
  return item?.uuid || item?.id || String(index)
}

/**
 * How close to the end of the shelf the member has to scroll before the next
 * window is requested. Roughly two tiles of runway — enough that the tiles are
 * there by the time they arrive, without prefetching a row nobody scrolled.
 */
const LOAD_AHEAD_PX = 600

/** Tiles per request once the shelf starts filling itself in. */
const PAGE_SIZE = 12

/**
 * One Discover row: a horizontal shelf that fills itself in as it is scrolled.
 *
 * The feed ships the head of each row and the row asks for the rest, so opening
 * Discover costs one window per shelf rather than every tile of every shelf. A
 * row that holds more than it will ever show ends in a link to its own page —
 * and only then, because a "see all" that leads to the same tiles is a lie.
 */
export function DiscoverShelf({
  section,
  isAdmin = false,
  showPlayStatus = false,
  enableDeleteOnDisk = false,
  pinned = false,
  canPin = true,
  onTogglePin,
  onHide,
}: LooseProps) {
  const identifier = String(section.identifier || '')
  const itemKind = section.item_kind || 'games'
  const totalCount = Number(section.total_count) || 0
  const [games, setGames] = useState(() => rowItems(section))
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(false)
  /** Custom bar metrics — native scrollbar is hidden so hover bleed can stay. */
  const [hbar, setHbar] = useState({ max: 0, thumbPx: 0, leftPx: 0, scrollLeft: 0 })
  const abortRef = useRef<any>(null)
  const hbarDragRef = useRef<any>(null)
  // Arrows + bottom slider. Vertical wheel on tiles/title scrolls the page;
  // horizontal / shift-wheel and wheel on the slider pan the track both ways.
  // The lane always mounts so spacing matches every row, even when the track
  // does not overflow.
  const {
    ref: trackRef,
    viewportRef,
    hbarRef,
    overflow,
    measure,
    scrollByPage,
    startEdgeScroll,
    stopEdgeScroll,
  } = useRowScroll({ bindKey: games.length, wrapAround: true })

  const syncHbar = useCallback(() => {
    const track = trackRef.current
    const rail = hbarRef.current
    if (!track) return
    setHbar({
      ...hbarLayout({
        scrollLeft: track.scrollLeft,
        scrollWidth: track.scrollWidth,
        clientWidth: track.clientWidth,
        railWidth: rail?.clientWidth || 0,
      }),
      scrollLeft: track.scrollLeft,
    })
  }, [hbarRef, trackRef])

  // A fresh feed replaces the row wholesale rather than appending to whatever
  // the previous one had scrolled to.
  useEffect(() => {
    setGames(rowItems(section))
    setLoadError(false)
  }, [section])

  useEffect(() => () => abortRef.current?.abort(), [])

  useLayoutEffect(() => {
    const track = trackRef.current
    const rail = hbarRef.current
    syncHbar()
    if (!track || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(syncHbar)
    observer.observe(track)
    if (rail) observer.observe(rail)
    for (const child of track.children) observer.observe(child)
    return () => observer.disconnect()
  }, [games.length, loading, hbarRef, syncHbar, trackRef])

  const complete = games.length >= totalCount

  /* Mark which tiles are fully inside the track. Clipped edge tiles must not
     enlarge on hover — the scale would grow into (and be cut by) the scroll
     clip, which is the broken half-cover the member sees at the row end. */
  useEffect(() => {
    const track = trackRef.current
    if (!track || typeof IntersectionObserver === 'undefined') return undefined

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          entry.target.toggleAttribute(
            'data-fully-visible',
            isShelfItemFullyVisible(entry.intersectionRatio),
          )
        }
      },
      { root: track, threshold: [0, 0.5, 0.99, 1] },
    )

    const items = track.querySelectorAll('.od-shelf__item')
    // Assume fully visible until the observer reports otherwise so News tiles
    // (which only cancel enlarge when the attribute is absent) can hover-scale
    // on the first paint the way game tiles do via theme CSS.
    items.forEach((node: any) => {
      node.toggleAttribute('data-fully-visible', true)
      observer.observe(node)
    })
    return () => observer.disconnect()
  }, [games.length, loading, complete, trackRef])

  const loadMore = useCallback(() => {
    if (loading || loadError || complete || !identifier) {
      return
    }
    setLoading(true)
    const controller = new AbortController()
    abortRef.current = controller
    fetchDiscoverRow(identifier, {
      offset: games.length,
      limit: PAGE_SIZE,
      feedToken: section.feed_token,
      signal: controller.signal,
    })
      .then((page) => {
        setGames((current: any) => {
          // Concurrent loads and a re-render can both land here; keying by
          // identity means an overlapping window adds nothing rather than
          // duplicating a tile halfway down the shelf.
          const seen = new Set(current.map((item: any) => itemKey(item)))
          return current.concat(page.items.filter((item: any) => !seen.has(itemKey(item))))
        })
        setLoading(false)
      })
      .catch((err: any) => {
        if (err?.name === 'AbortError') return
        // A shelf that cannot fill itself keeps what it has and stops asking.
        // The tiles already there still work.
        setLoadError(true)
        setLoading(false)
      })
  }, [complete, games.length, identifier, loadError, loading, section.feed_token])

  const handleScroll = useCallback(() => {
    const track = trackRef.current
    if (!track) return
    measure()
    syncHbar()
    const remaining = track.scrollWidth - track.scrollLeft - track.clientWidth
    if (remaining <= LOAD_AHEAD_PX) {
      loadMore()
    }
  }, [loadMore, measure, syncHbar, trackRef])

  const onHbarPointerDown = useCallback(
    (event: any) => {
      const track = trackRef.current
      const rail = event.currentTarget
      if (!track) return

      const liveLayout = () =>
        hbarLayout({
          scrollLeft: track.scrollLeft,
          scrollWidth: track.scrollWidth,
          clientWidth: track.clientWidth,
          railWidth: rail.getBoundingClientRect().width,
        })

      const start = liveLayout()
      if (start.max <= 1) return
      event.preventDefault()
      event.stopPropagation()
      if (typeof rail.setPointerCapture === 'function' && event.pointerId != null) {
        try {
          rail.setPointerCapture(event.pointerId)
        } catch {
          // Pointer already released — window listeners below still finish the drag.
        }
      }

      const railBox = rail.getBoundingClientRect()
      let grab = event.clientX - railBox.left - start.leftPx
      if (grab < 0 || grab > start.thumbPx) {
        grab = start.thumbPx / 2
      }

      const scrollFromClientX = (clientX: any) => {
        const layout = liveLayout()
        if (layout.max <= 1 || layout.usable <= 0) return
        const box = rail.getBoundingClientRect()
        track.scrollLeft = scrollLeftFromPointer({
          clientX,
          railLeft: box.left,
          grab,
          usable: layout.usable,
          max: layout.max,
        })
        measure()
        syncHbar()
      }

      scrollFromClientX(event.clientX)
      hbarDragRef.current = { scrollFromClientX }
      const onMove = (ev: any) => hbarDragRef.current?.scrollFromClientX(ev.clientX)
      const onUp = () => {
        hbarDragRef.current = null
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
      }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
    },
    [measure, syncHbar, trackRef],
  )

  if (!games.length) {
    return null
  }

  const layout = section.layout || 'shelf'
  const moreHref = itemKind === 'articles' ? section.more_href || '/news' : section.more_href
  const showSeeAll = Boolean(moreHref) && (itemKind === 'articles' || Boolean(section.has_more))

  return (
    <section
      data-discover-section={identifier}
      data-layout={layout}
      data-item-kind={itemKind}
      className={`od-shelf od-shelf--${layout}`}
    >
      <div className="od-shelf__head">
        {/* Title mark + reason share a baseline row; the h2 keeps only the
            section name so screen readers still hear "News", not the lede. */}
        <div className="od-shelf__heading">
          <h2 className="od-shelf__title">
            <span className="od-shelf__title-text">{section.title}</span>
          </h2>
          {section.reason ? <span className="od-shelf__reason">{section.reason}</span> : null}
        </div>
        {section.is_event ? (
          <span className="od-shelf__event" title="Limited-time shelf">
            Event{formatEventEnds(section.ends_at)}
          </span>
        ) : null}
        {onTogglePin ? (
          <button
            type="button"
            className="od-shelf__pin"
            aria-pressed={pinned}
            // A member gets a fixed number of pins, so the control that would
            // exceed it is disabled rather than silently doing nothing.
            disabled={!pinned && !canPin}
            title={
              pinned
                ? 'Unpin this row'
                : canPin
                  ? 'Pin this row to the top'
                  : 'You have pinned as many rows as you can'
            }
            onClick={() => onTogglePin(identifier)}
          >
            {pinned ? 'Pinned' : 'Pin'}
          </button>
        ) : null}
        {onHide ? (
          <button
            type="button"
            className="od-shelf__hide"
            /* Hiding is reversible and the way back has to be visible from
               here, or a row put away is a row gone for good — the control
               says where it went. */
            title="Hide this row (restore it from Discover’s row settings)"
            onClick={() => onHide(identifier)}
          >
            Hide
          </button>
        ) : null}
        {showSeeAll ? (
          <Link className="od-shelf__seeall" to={moreHref}>
            See all
          </Link>
        ) : null}
      </div>

      <div className="od-shelf__scroller" ref={viewportRef}>
        <div className="od-shelf__viewport">
          {/* Rendered whether or not they are usable, and disabled when they are
              not: arrows that appear and disappear as a row fills itself in move
              the tiles under the pointer mid-reach. Hover holds a slow scroll. */}
          <button
            type="button"
            className="od-shelf__arrow od-shelf__arrow--start"
            aria-label={`Scroll ${section.title} left`}
            disabled={!overflow.start && !overflow.end}
            onClick={() => scrollByPage(-1)}
            onPointerEnter={() => {
              if (overflow.start) startEdgeScroll(-1)
            }}
            onPointerLeave={stopEdgeScroll}
          >
            <span aria-hidden="true">‹</span>
          </button>

          <div
            className="od-shelf__track"
            ref={trackRef}
            onScroll={handleScroll}
            role="list"
            aria-label={section.title}
          >
            {games.map((item: any, index: any) => (
              <div className="od-shelf__item" role="listitem" key={itemKey(item, index)}>
                {itemKind === 'articles' ? (
                  <NewsCard item={item} />
                ) : (
                  <GameCard
                    game={item}
                    discoverReason={section.reason}
                    isAdmin={isAdmin}
                    showPlayStatus={showPlayStatus}
                    enableDeleteOnDisk={enableDeleteOnDisk}
                  />
                )}
              </div>
            ))}

            {loading ? (
              <div className="od-shelf__item od-shelf__pending" aria-hidden="true" />
            ) : null}

            {showSeeAll ? (
              <Link
                className="od-shelf__item od-shelf__more"
                to={moreHref}
                aria-label={`See all in ${section.title}`}
              >
                <span className="od-shelf__more-mark" aria-hidden="true">
                  +
                </span>
                <span className="od-shelf__more-label">See all</span>
              </Link>
            ) : null}
          </div>

          <button
            type="button"
            className="od-shelf__arrow od-shelf__arrow--end"
            aria-label={`Scroll ${section.title} right`}
            disabled={!overflow.start && !overflow.end}
            onClick={() => scrollByPage(1)}
            onPointerEnter={() => {
              if (overflow.end) startEdgeScroll(1)
            }}
            onPointerLeave={stopEdgeScroll}
          >
            <span aria-hidden="true">›</span>
          </button>
        </div>

        <div
          ref={hbarRef}
          className="od-shelf__hbar"
          data-idle={hbar.max <= 1 ? 'true' : undefined}
          role="scrollbar"
          aria-label={`Scroll ${section.title}`}
          aria-orientation="horizontal"
          aria-disabled={hbar.max <= 1}
          aria-valuemin={0}
          aria-valuemax={Math.round(Math.max(hbar.max, 0))}
          aria-valuenow={Math.round(hbar.scrollLeft || 0)}
          onPointerDown={onHbarPointerDown}
        >
          <div
            className="od-shelf__hbar-thumb"
            style={{
              width: hbar.thumbPx > 0 ? `${hbar.thumbPx}px` : '100%',
              left: `${hbar.leftPx}px`,
            }}
          />
        </div>
      </div>
    </section>
  )
}

/** " · ends in 3 days" — omitted entirely when there is no honest end date. */
export function formatEventEnds(endsAt: any) {
  if (!endsAt) return ''
  const end = new Date(endsAt)
  if (Number.isNaN(end.getTime())) return ''
  const msLeft = end.getTime() - Date.now()
  if (msLeft <= 0) return ''
  const days = Math.floor(msLeft / 86_400_000)
  if (days >= 2) return ` · ends in ${days} days`
  const hours = Math.max(1, Math.floor(msLeft / 3_600_000))
  return ` · ends in ${hours} hour${hours === 1 ? '' : 's'}`
}
