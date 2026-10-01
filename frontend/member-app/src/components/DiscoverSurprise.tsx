import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@oneirodex/ui'
import { fetchSurprise, type SurpriseGenre } from '../api/discover'
import { GameCard } from './GameCard'
import './DiscoverSurprise.css'

/** How many recent picks "another" asks the server not to repeat. */
const RECENT_LIMIT = 20

interface DiscoverSurpriseProps {
  isAdmin?: boolean
  showPlayStatus?: boolean
  enableDeleteOnDisk?: boolean
}

/**
 * *Surprise me* (INSP-4b): one title from the top of the member's own ranking,
 * steered by their strongest genres.
 *
 * Nothing is drawn until the member asks — a pick that changes on every visit
 * to Discover is noise, and a pick made on load is a request the member did
 * not make. The genre chips load up front because they are the offer.
 */
export function DiscoverSurprise({
  isAdmin = false,
  showPlayStatus = false,
  enableDeleteOnDisk = false,
}: DiscoverSurpriseProps) {
  const [genres, setGenres] = useState<SurpriseGenre[]>([])
  const [genre, setGenre] = useState<number | null>(null)
  const [game, setGame] = useState<Record<string, unknown> | null>(null)
  const [reason, setReason] = useState('')
  const [drawn, setDrawn] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const recent = useRef<string[]>([])

  useEffect(() => {
    const controller = new AbortController()
    // The chips ride on a draw we then discard: one route, no second endpoint
    // for a list the draw already computes.
    fetchSurprise({ signal: controller.signal })
      .then((pick) => setGenres(pick.genres))
      .catch(() => {
        /* No chips is fine; the button still works. */
      })
    return () => controller.abort()
  }, [])

  const draw = useCallback((nextGenre: number | null) => {
    setBusy(true)
    setFailed(false)
    fetchSurprise({ genre: nextGenre, exclude: recent.current })
      .then((pick) => {
        const uuid = typeof pick.game?.uuid === 'string' ? pick.game.uuid : ''
        if (uuid) recent.current = [uuid, ...recent.current].slice(0, RECENT_LIMIT)
        setGame(pick.game)
        setReason(pick.reason)
        setDrawn(true)
      })
      .catch(() => setFailed(true))
      .finally(() => setBusy(false))
  }, [])

  const chooseGenre = useCallback(
    (id: number) => {
      const next = genre === id ? null : id
      setGenre(next)
      // Steering is a request for a pick in that genre, so it draws at once
      // rather than waiting for a second press.
      draw(next)
    },
    [draw, genre],
  )

  return (
    <section className="od-surprise" aria-labelledby="od-surprise-title">
      <div className="od-surprise__head">
        <h2 id="od-surprise-title" className="od-surprise__title">
          Surprise me
        </h2>
        <Button size="sm" onClick={() => draw(genre)} disabled={busy}>
          {drawn ? 'Another' : 'Pick something'}
        </Button>
      </div>

      {genres.length ? (
        <div className="od-surprise__genres" role="group" aria-label="Steer by genre">
          {genres.map((option) => {
            const active = genre === option.id
            return (
              <button
                key={option.id}
                type="button"
                className={`od-surprise__genre${active ? ' is-active' : ''}`}
                aria-pressed={active}
                onClick={() => chooseGenre(option.id)}
              >
                {option.name}
              </button>
            )
          })}
        </div>
      ) : null}

      <div className="od-surprise__result" aria-live="polite">
        {failed ? <p className="od-surprise__note">Couldn’t pick right now. Try again.</p> : null}
        {!failed && drawn && game ? (
          <div className="od-surprise__card">
            <GameCard
              game={game}
              discoverReason={reason}
              isAdmin={isAdmin}
              showPlayStatus={showPlayStatus}
              enableDeleteOnDisk={enableDeleteOnDisk}
            />
          </div>
        ) : null}
        {!failed && drawn && !game ? <p className="od-surprise__note">{reason}</p> : null}
      </div>
    </section>
  )
}
