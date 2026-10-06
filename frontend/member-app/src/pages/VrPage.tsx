import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ContextBar } from '../chrome/ContextBar'
import { usesNewChrome } from '../chrome/usesNewChrome'
import { useShellConfig } from '@oneirodex/ui'
import { fetchVrCatalog, fetchVrGame } from '../api/vr'
import { VrWayToPlayLine, vrCompatCopy } from '../components/VrWayToPlay'
import { PageStatus } from '../components/PageStatus'
import './VrPage.css'

const PER_PAGE = 48
const VR_VIEWS = [
  { id: 'all', label: 'All' },
  { id: 'native_vr', label: 'Native VR' },
  { id: 'injector_profile', label: 'Community profile' },
]

export function VrPage() {
  const shellConfig = useShellConfig()
  const useNewChrome = usesNewChrome(shellConfig)
  const [catalog, setCatalog] = useState<any>(null)
  const [error, setError] = useState<any>(null)
  const [page, setPage] = useState(1)
  const [retryCount, setRetryCount] = useState(0)
  const [selectedUuid, setSelectedUuid] = useState<any>(null)
  const [detail, setDetail] = useState<any>(null)
  const [detailError, setDetailError] = useState<any>(null)
  // Rider R3: `?vr_compat=native_vr|injector_profile` narrows the hub to one way to play.
  const [searchParams, setSearchParams] = useSearchParams()
  const vrCompatFilter = searchParams.get('vr_compat') || ''

  const selectVrView = (value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value === 'all') next.delete('vr_compat')
    else next.set('vr_compat', value)
    setSearchParams(next, { replace: true })
    setPage(1)
  }

  useEffect(() => {
    if (!('serviceWorker' in navigator)) {
      return
    }
    navigator.serviceWorker.register('/vr/sw.js', { scope: '/vr' }).catch(() => {
      // The PWA shell is optional; browsing still works without it.
    })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setError(null)
    setCatalog(null)

    fetchVrCatalog({ signal: controller.signal, page, perPage: PER_PAGE, vrCompat: vrCompatFilter })
      .then((data) => {
        if (active) {
          setCatalog(data)
        }
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
  }, [page, retryCount, vrCompatFilter])

  useEffect(() => {
    if (!selectedUuid) {
      return undefined
    }

    const controller = new AbortController()
    let active = true
    setDetailError(null)
    setDetail(null)

    fetchVrGame(selectedUuid, { signal: controller.signal })
      .then((data) => {
        if (active) {
          setDetail(data)
        }
      })
      .catch((err: any) => {
        if (active && err.name !== 'AbortError') {
          setDetailError(err)
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [selectedUuid])

  const games = catalog?.games || []

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
      <p className="od-more-page__lede">
        Large-tap browse for headset browsers. Install as a PWA from the browser menu. Browse only —
        no downloads.
      </p>

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
        loading={!error && !catalog}
        error={error}
        errorMessage="Unable to load the VR catalog."
        loadingMessage="Loading VR catalog…"
        onRetry={() => setRetryCount((n) => n + 1)}
      />

      {!error && catalog ? <p className="od-vr__status">{catalog.total || 0} games</p> : null}

      {!error && catalog && games.length === 0 ? (
        <p>No games are available for VR browsing yet.</p>
      ) : null}

      {!error && games.length > 0 ? (
        <div className="od-vr__grid">
          {games.map((game: any) => (
            <button
              key={game.uuid}
              type="button"
              className="od-vr__card"
              data-uuid={game.uuid}
              onClick={() => setSelectedUuid(game.uuid)}
            >
              {game.cover_url ? <img src={game.cover_url} alt="" loading="lazy" /> : null}
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
            Page {catalog.page} of {catalog.pages}
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
            loading={!detailError && !detail}
            error={detailError}
            errorMessage="Unable to load this game."
            loadingMessage="Loading game…"
          />

          {!detailError && detail ? (
            <>
              {detail.cover_url ? (
                <img className="od-vr__detail-cover" src={detail.cover_url} alt="" />
              ) : null}
              <h2>{detail.name}</h2>
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
