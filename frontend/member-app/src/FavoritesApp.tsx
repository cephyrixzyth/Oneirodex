import { useEffect, useMemo, useState } from 'react'
import { fetchFavoriteGames } from './api/favorites'
import { ContextBar } from './chrome/ContextBar'
import { GameGrid } from './components/GameGrid'
import { ITEM_KIND_FILTER_CHIPS } from './components/ItemKindFilterChips'
import { PaginationBar } from './components/PaginationBar'
import { PageStatus } from './components/PageStatus'
import { CATALOG_LAYOUTS, useCatalogLayout } from './utils/catalogLayout'

export function FavoritesApp({ initialConfig }: LooseProps = {}) {
  // perPage rides in on initialConfig now (App builds it from useShellConfig()),
  // so this view stays purely initialConfig-driven — no context of its own.
  const defaultPerPage = Number(initialConfig?.perPage) || 50
  const [games, setGames] = useState<any>(null)
  const [error, setError] = useState<any>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(defaultPerPage)
  const [pages, setPages] = useState(1)
  const [total, setTotal] = useState(0)
  /* Favorites is a library, and a big one for anyone who has been using the
     product a while — so it needs both of the ways Library gives you through a
     long list: narrow it, or page it. The pager was already here; narrowing was
     not, so a member with four hundred favourites could only scroll.

     Name and kind, and nothing else, because those are exactly what
     `GET /api/favorites` supports (`apply_name_filter` / `apply_item_kind_filter`
     on that route). Offering a control the endpoint cannot honour would be the
     tile-size slider problem again — a filter that moves and changes nothing. */
  const [name, setName] = useState('')
  const [itemKind, setItemKind] = useState('')
  const [layout, setLayout] = useCatalogLayout()

  useEffect(() => {
    const controller = new AbortController()
    let active = true

    setError(null)
    setGames(null)
    fetchFavoriteGames(
      { page, per_page: perPage, name, item_kind: itemKind },
      { signal: controller.signal },
    )
      .then((result) => {
        if (!active) return
        setGames(result.games ?? [])
        setPages(Number(result.pages) || 1)
        setTotal(Number(result.total) || 0)
      })
      .catch((requestError: any) => {
        if (active && requestError.name !== 'AbortError') {
          setError(requestError)
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [page, perPage, retryCount, name, itemKind])

  const kindViews = useMemo(
    () => [
      { id: '', label: 'All' },
      ...ITEM_KIND_FILTER_CHIPS.map((chip) => ({ id: chip.kind, label: chip.label })),
    ],
    [],
  )

  /* Only the search counts toward the badge. The kind is the segmented strip in
     the open, so counting it would badge the trigger for a filter that is
     already visible — the same miscount Library's bar deliberately avoids. */
  const filterCount = name ? 1 : 0

  const bar = (
    <ContextBar
      views={kindViews}
      activeView={itemKind}
      onSelectView={(kind: any) => {
        setPage(1)
        setItemKind(kind || '')
      }}
      filterCount={filterCount}
      filters={({ close }: LooseProps) => (
        <form
          className="od-favorites__filters"
          onSubmit={(event) => {
            event.preventDefault()
            close()
          }}
        >
          <label>
            <span className="visually-hidden">Search favorites by title</span>
            <input
              type="search"
              className="form-control"
              placeholder="Search by title"
              aria-label="Search favorites by title"
              autoComplete="off"
              value={name}
              onChange={(event) => {
                setPage(1)
                setName(event.target.value)
              }}
            />
          </label>
          <div className="od-cbtn-group od-cbtn-group--fill">
            <button
              type="button"
              className="od-cbtn"
              disabled={!name}
              onClick={() => {
                setPage(1)
                setName('')
              }}
            >
              Clear
            </button>
            <button type="submit" className="od-cbtn">
              Done
            </button>
          </div>
        </form>
      )}
      summary={total ? `${total.toLocaleString()} favorites` : null}
      viewUnfurl={{
        views: CATALOG_LAYOUTS,
        active: layout,
        onSelect: setLayout,
        triggerLabel: 'View',
      }}
    />
  )

  if (error || !games) {
    return (
      <>
        {bar}
        <PageStatus
          loading={!error}
          error={error}
          errorMessage="Unable to load favorites."
          loadingMessage="Loading favorites…"
          onRetry={() => setRetryCount((count) => count + 1)}
        />
      </>
    )
  }

  // "Nothing matched" and "you have none" are different answers, and telling a
  // member they have no favourites while they are looking at a search box they
  // just typed into is the wrong one. Plain text like Downloads — no status box.
  if (games.length === 0) {
    return (
      <>
        {bar}
        <p className="od-favorites-empty">
          {name || itemKind
            ? 'No favorites match that. Clear the filter to see them all.'
            : "You haven't added any favorites yet!"}
        </p>
      </>
    )
  }

  return (
    <>
      {bar}
      <GameGrid
        games={games}
        showPlayStatus={initialConfig.showPlayStatus}
        isAdmin={initialConfig.isAdmin}
        layout={layout}
        onToggleFavorite={(gameUuid: any, isFavorite: any) => {
          if (!isFavorite) {
            if (games.length === 1 && page > 1) {
              // Removing the only row on a later page can make that page
              // disappear. Reload the now-last page instead of presenting an
              // empty-favorites message while earlier pages still have rows.
              setPage(page - 1)
            } else {
              setGames((currentGames: any) =>
                currentGames.filter((game: any) => game.uuid !== gameUuid),
              )
            }
            setTotal((n) => Math.max(0, n - 1))
          }
        }}
      />
      <PaginationBar
        page={page}
        pages={pages}
        perPage={perPage}
        onPageChange={setPage}
        onPerPageChange={(next: any) => {
          setPage(1)
          setPerPage(next)
        }}
      />
    </>
  )
}
