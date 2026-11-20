import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ContextBar } from '../chrome/ContextBar'
import { usesNewChrome } from '../chrome/usesNewChrome'
import { useShellConfig, useViewer } from '@oneirodex/ui'
import { toggleFavorite } from '../api/userActions'
import { fetchVrCatalog, fetchVrGame } from '../api/vr'
import { VrWayToPlayLine, vrCompatCopy, type VrCompat } from '../components/VrWayToPlay'
import { PageStatus } from '../components/PageStatus'
import { CoverFallback } from '../components/CoverFallback'
import { LibraryRoom } from './LibraryRoom'
import './VrPage.css'

interface VrGame {
  is_favorite?: boolean
  uuid: string
  name: string
  cover_url?: string | null
  vr_compat?: VrCompat
  size?: string | null
  summary?: string | null
}

interface VrCatalog {
  games: VrGame[]
  total: number
  pages: number
  page?: number
}

function VrCover({ game, className = '' }: { game: VrGame; className?: string }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [game.cover_url])
  const url = String(game.cover_url || '')
  const isRetiredPlaceholder = url.replace(/\\/g, '/').toLowerCase().endsWith('default_cover.jpg')
  const hasArt = Boolean(url) && !isRetiredPlaceholder && !failed

  return hasArt ? (
    <img className={className} src={url} alt="" loading="lazy" onError={() => setFailed(true)} />
  ) : (
    <CoverFallback name={game.name} />
  )
}

const PER_PAGE = 48
const VR_VIEWS = [
  { id: 'all', label: 'VR titles' },
  { id: 'collection', label: 'Full library' },
  { id: 'favorites', label: 'Favorites' },
  { id: 'native_vr', label: 'Native VR' },
  { id: 'injector_profile', label: 'Community profile' },
]

export function VrPage() {
  const shellConfig = useShellConfig()
  const { userId } = useViewer()
  const useNewChrome = usesNewChrome(shellConfig)
  const [catalog, setCatalog] = useState<VrCatalog | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [page, setPage] = useState(1)
  const [retryCount, setRetryCount] = useState(0)
  const [selectedUuid, setSelectedUuid] = useState<string | null>(null)
  const [detail, setDetail] = useState<VrGame | null>(null)
  const favoriteBusy = useRef(false)
  const [favoriteMessage, setFavoriteMessage] = useState('')
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [detailError, setDetailError] = useState<unknown>(null)
  // Rider R3: `?vr_compat=native_vr|injector_profile` narrows the hub to one way to play.
  const [searchParams, setSearchParams] = useSearchParams()
  const vrCompatFilter = searchParams.get('vr_compat') || ''

  async function changeFavorite() {
    if (!detail || detail.uuid !== selectedUuid || favoriteBusy.current) return
    const id = detail.uuid
    favoriteBusy.current = true
    setFavoriteMessage('Saving favorite…')
    try {
      const result = await toggleFavorite(id)
      setDetail((current) =>
        current?.uuid === id ? { ...current, is_favorite: Boolean(result.is_favorite) } : current,
      )
      setFavoriteMessage('')
      if (vrCompatFilter === 'favorites') setRetryCount((n) => n + 1)
    } catch {
      setFavoriteMessage('Could not confirm the favorite. Reloading its saved state.')
      setDetailAttempt((n) => n + 1)
    } finally {
      favoriteBusy.current = false
    }
  }
  function selectGame(id: string | null) {
    setFavoriteMessage('')
    setSelectedUuid(id)
  }
  const selectVrView = (value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value === 'all') next.delete('vr_compat')
    else next.set('vr_compat', value)
    setSelectedUuid(null)
    setSearchParams(next, { replace: true })
    setPage(1)
  }

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setError(null)
    setCatalog(null)

    fetchVrCatalog({ signal: controller.signal, page, perPage: PER_PAGE, vrCompat: vrCompatFilter })
      .then((data) => {
        if (active) {
          const result = data as VrCatalog
          if (page > Math.max(1, result.pages)) setPage(Math.max(1, result.pages))
          else setCatalog(result)
        }
      })
      .catch((err: unknown) => {
        if (active && !(err instanceof Error && err.name === 'AbortError')) {
          setError(err)
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [page, retryCount, vrCompatFilter])

  useEffect(() => {
    if (!selectedUuid) {
      return undefined
    }

    const controller = new AbortController()
    let active = true
    setDetailError(null)
    setDetail(null)

    fetchVrGame(selectedUuid, {
      signal: controller.signal,
      collection: ['collection', 'favorites'].includes(vrCompatFilter),
    })
      .then((data) => {
        if (active) {
          setDetail(data as VrGame)
        }
      })
      .catch((err: unknown) => {
        if (active && !(err instanceof Error && err.name === 'AbortError')) {
          setDetailError(err)
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [selectedUuid, vrCompatFilter, detailAttempt])

  const games = catalog?.games ?? []

  return (
    <div className="od-more-page od-vr">
      {useNewChrome ? (
        <ContextBar
          views={VR_VIEWS}
          activeView={vrCompatFilter || 'all'}
          onSelectView={selectVrView}
        />
      ) : (
        <div className="od-page-header">
          <h1>VR Library</h1>
        </div>
      )}
      <LibraryRoom
        key={String(userId ?? 'guest')}
        memberId={String(userId ?? '')}
        initiallyOpen={searchParams.get('room') === 'open'}
        scope={vrCompatFilter}
        onFavorites={() => selectVrView('favorites')}
        onScope={() => selectVrView(vrCompatFilter === 'collection' ? 'all' : 'collection')}
        games={games}
        page={page}
        pages={catalog?.pages || 1}
        total={catalog?.total || 0}
        pageSize={PER_PAGE}
        ready={Boolean(catalog)}
        error={Boolean(error)}
        selected={selectedUuid ? detail : null}
        detailMessage={
          selectedUuid && detailError
            ? 'Unable to load this game.'
            : selectedUuid && !detail
              ? 'Loading game…'
              : ''
        }
        onFavorite={() => void changeFavorite()}
        favoriteMessage={favoriteMessage}
        onSelect={selectGame}
        onPage={setPage}
      />

      {useNewChrome ? null : (
        <div className="od-cbtn-group od-vr__ways" role="group" aria-label="Way to play">
          {VR_VIEWS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              className={`od-cbtn${(vrCompatFilter || 'all') === id ? ' is-on' : ''}`}
              aria-pressed={(vrCompatFilter || 'all') === id}
              onClick={() => selectVrView(id)}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <PageStatus
        inline
        loading={!error && !catalog}
        error={error}
        errorMessage="Unable to load the VR catalog."
        loadingMessage="Loading VR catalog…"
        onRetry={() => setRetryCount((n) => n + 1)}
      />

      {!error && catalog ? <p className="od-vr__status">{catalog.total || 0} games</p> : null}

      {!error && catalog && games.length === 0 ? (
        <p>
          {vrCompatFilter === 'favorites'
            ? 'Favorite a title at the reading desk to place it on this shelf.'
            : vrCompatFilter === 'collection'
              ? 'Your library has no visible titles yet.'
              : 'No games are available for VR browsing yet.'}
        </p>
      ) : null}

      {!error && games.length > 0 ? (
        <div className="od-vr__grid">
          {games.map((game) => (
            <button
              key={game.uuid}
              type="button"
              className="od-vr__card"
              data-uuid={game.uuid}
              onClick={() => selectGame(game.uuid)}
            >
              <VrCover game={game} />
              <span>{game.name}</span>
              {game.vr_compat === 'injector_profile' ? (
                <small className="od-vr__card-way" title={vrCompatCopy('injector_profile')?.title}>
                  community profile
                </small>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}

      {!error && catalog && catalog.pages > 1 ? (
        <nav className="od-vr__pager" aria-label="Catalog pages">
          <button
            type="button"
            className="od-cbtn"
            disabled={page <= 1}
            onClick={() => setPage((n) => n - 1)}
          >
            Previous
          </button>
          <span>
            Page {catalog.page ?? page} of {catalog.pages}
          </span>
          <button
            type="button"
            className="od-cbtn"
            disabled={page >= catalog.pages}
            onClick={() => setPage((n) => n + 1)}
          >
            Next
          </button>
        </nav>
      ) : null}

      {selectedUuid ? (
        <div className="od-vr__detail">
          <button type="button" className="od-vr__back" onClick={() => setSelectedUuid(null)}>
            Back
          </button>

          <PageStatus
            inline
            loading={!detailError && !detail}
            error={detailError}
            errorMessage="Unable to load this game."
            onRetry={() => setDetailAttempt((n) => n + 1)}
            loadingMessage="Loading game…"
          />

          {!detailError && detail ? (
            <>
              <VrCover game={detail} className="od-vr__detail-cover" />
              <h2>{detail.name}</h2>
              <button
                className="od-cbtn"
                type="button"
                aria-pressed={Boolean(detail.is_favorite)}
                onClick={() => void changeFavorite()}
                disabled={favoriteBusy.current}
              >
                {detail.is_favorite ? 'Remove favorite' : 'Add favorite'}
              </button>
              {favoriteMessage && <span role="status">{favoriteMessage}</span>}
              {detail.size ? <p className="od-vr__meta">{detail.size}</p> : null}
              <VrWayToPlayLine vrCompat={detail.vr_compat} />
              <p>{detail.summary || 'No summary'}</p>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
