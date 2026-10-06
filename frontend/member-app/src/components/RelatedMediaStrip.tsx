import { useCallback, useEffect, useState } from 'react'
import { fetchRelatedMedia } from '../api/gameDetails'
import { safeHttpUrl } from '../utils/safeUrl'
import './RelatedMediaStrip.css'

/**
 * Media attached to a game — adaptations, tie-ins, soundtracks.
 *
 * Context, not tracking: nothing here is rated or progressed. Each item opens a
 * popup with the detail and a link out to where it legitimately lives.
 *
 * Renders nothing at all when a game has no related media, so the detail page
 * does not grow an empty section for the overwhelming majority of titles.
 */

const KIND_ICON: Record<string, string> = {
  film: '🎬',
  series: '📺',
  anime: '🌸',
  book: '📖',
  comic: '💥',
  music: '🎵',
  podcast: '🎙️',
}

export function RelatedMediaStrip({ gameUuid }: LooseProps) {
  const [items, setItems] = useState<any[]>([])
  const [kinds, setKinds] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState<any>(null)
  const [filter, setFilter] = useState('all')

  const load = useCallback(async () => {
    if (!gameUuid) return
    setLoading(true)
    try {
      const data = (await fetchRelatedMedia(gameUuid)) ?? {}
      setItems(Array.isArray(data.items) ? data.items : [])
      setKinds(Array.isArray(data.kinds) ? data.kinds : [])
    } catch {
      // Related media is a bonus surface — a failure here must not shout on a
      // page whose main job is the game itself.
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [gameUuid])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!active) return undefined
    const onKey = (event: any) => {
      if (event.key === 'Escape') setActive(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [active])

  if (loading || items.length === 0) {
    return null
  }

  const kindLabel = (id: any) => kinds.find((k) => k.id === id)?.label || id
  const present = [...new Set(items.map((i) => i.media_kind))]
  const shown = filter === 'all' ? items : items.filter((i) => i.media_kind === filter)

  return (
    <section className="od-relmedia" aria-labelledby="od-relmedia-heading">
      <div className="od-relmedia__head">
        <h2 id="od-relmedia-heading">Related media</h2>
        <span className="od-relmedia__count">{items.length}</span>
      </div>
      <p className="od-relmedia__lede">
        Adaptations, tie-ins and soundtracks connected to this game.
      </p>

      {present.length > 1 ? (
        <div className="od-relmedia__filters" role="group" aria-label="Filter related media">
          <button
            type="button"
            className={`od-chip${filter === 'all' ? ' is-active' : ''}`}
            aria-pressed={filter === 'all'}
            onClick={() => setFilter('all')}
          >
            All
          </button>
          {present.map((kind) => (
            <button
              key={kind}
              type="button"
              className={`od-chip${filter === kind ? ' is-active' : ''}`}
              aria-pressed={filter === kind}
              onClick={() => setFilter(kind)}
            >
              <span aria-hidden="true">{KIND_ICON[kind] || '•'}</span> {kindLabel(kind)}
            </button>
          ))}
        </div>
      ) : null}

      <ul className="od-relmedia__list">
        {shown.map((item) => (
          <li key={item.id}>
            <button type="button" className="od-relmedia__card" onClick={() => setActive(item)}>
              {item.cover_url ? (
                <img
                  className="od-relmedia__art"
                  src={item.cover_url}
                  alt=""
                  loading="lazy"
                  onError={(e) => e.currentTarget.classList.add('is-broken')}
                />
              ) : (
                <span className="od-relmedia__art od-relmedia__art--empty" aria-hidden="true">
                  {KIND_ICON[item.media_kind] || '•'}
                </span>
              )}
              <span className="od-relmedia__card-body">
                <span className="od-relmedia__kind">
                  {KIND_ICON[item.media_kind] || '•'} {kindLabel(item.media_kind)}
                </span>
                <strong className="od-relmedia__title">{item.title}</strong>
                {item.year ? <span className="od-relmedia__year">{item.year}</span> : null}
              </span>
            </button>
          </li>
        ))}
      </ul>

      {active ? (
        <div
          className="od-relmedia__scrim"
          role="presentation"
          onClick={(e) => {
            if (e.target === e.currentTarget) setActive(null)
          }}
        >
          <div
            className="od-relmedia__modal"
            role="dialog"
            aria-modal="true"
            aria-label={active.title}
          >
            <button
              type="button"
              className="od-relmedia__close"
              aria-label="Close"
              onClick={() => setActive(null)}
            >
              ×
            </button>

            <div className="od-relmedia__modal-body">
              {active.cover_url ? (
                <img className="od-relmedia__modal-art" src={active.cover_url} alt="" />
              ) : null}
              <div className="od-relmedia__modal-text">
                <span className="od-relmedia__kind">
                  {KIND_ICON[active.media_kind] || '•'} {kindLabel(active.media_kind)}
                </span>
                <h3>{active.title}</h3>
                <p className="od-relmedia__meta">
                  {[active.creator, active.year].filter(Boolean).join(' · ')}
                </p>
                {active.summary ? <p className="od-relmedia__summary">{active.summary}</p> : null}
                {safeHttpUrl(active.external_url) ? (
                  <a
                    className="od-btn od-btn--primary"
                    href={safeHttpUrl(active.external_url) || undefined}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Where to find it
                  </a>
                ) : (
                  <p className="od-relmedia__meta">No link recorded for this one.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}
