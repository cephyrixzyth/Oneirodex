import { useEffect, useId, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useSearchParams } from 'react-router-dom'
import { useShellConfig, useViewer } from '@oneirodex/ui'
import { fetchBrowseGames } from './api/browse'
import { applyPlatformSkin, clearPlatformSkin } from './chrome/platformSkins'
import { SystemBackdrop } from './chrome/SystemBackdrop'
import { usesNewChrome } from './chrome/usesNewChrome'
import { BADGE_FILTER_PARAMS, badgeFiltersFromSearchParams } from './components/BadgeFilterChips'
import {
  filtersFromSearchParams,
  OWNERSHIP_FILTER_KEYS,
  searchParamsHaveLibraryFilters,
  withLibraryParams,
} from './libraryQueryParams'
import {
  ITEM_KIND_FILTER_CHIPS,
  itemKindFromSearchParams,
  parseItemKindFilter,
} from './components/ItemKindFilterChips'
import { ContextBar } from './chrome/ContextBar'
import { cleanFilters, FilterBar } from './components/FilterBar'
import './components/libraryFilters.css'
import { GameGrid } from './components/GameGrid'
import { GameGridSkeleton } from './components/GameGridSkeleton'
import { LibrarySelectionBar } from './components/LibrarySelectionBar'
import { PageStatus } from './components/PageStatus'
import { PaginationBar } from './components/PaginationBar'
import { StoreSetupPrompt } from './components/stores/StoreSetupPrompt'
import { createTranslator } from './i18n'
import { useLibraryBatchActions } from './library/useLibraryBatchActions'
import { useLibrarySelection } from './library/useLibrarySelection'
import type { BrowseResult } from './library/libraryTypes'
import { CATALOG_LAYOUTS, useCatalogLayout } from './utils/catalogLayout'
import { readLibraryFilters, writeLibraryFilters } from './utils/cookies'

/**
 * Why the catalog is empty — three situations, three sentences (UID-043).
 *
 * The blank grid used to have two branches, so "no scan has ever run" and "a
 * scan ran and matched nothing" produced the same line. The shipped copy was
 * written to be *true* in both cases rather than useful in either, which left
 * an operator with a misconfigured scan path no hint that anything had gone
 * wrong. `scanHasRun` and `unmatchedCount` come from the shell payload.
 *
 * Voice follows UID-041: playful while nothing is wrong (no library yet,
 * nothing scanned yet), plain once something has actually failed.
 */
function EmptyState({ initialConfig, t }: LooseProps) {
  if (initialConfig.libraryCount === 0) {
    return (
      <p>
        {initialConfig.isAdmin
          ? t('No libraries found. Add a library to get started.')
          : t('No libraries are available.')}
      </p>
    )
  }

  if (initialConfig.gamesCount === 0) {
    // A scan has run and still nothing landed — that is a fault to report, not
    // an empty shelf to be cheerful about.
    if (initialConfig.scanHasRun) {
      const unmatched = initialConfig.unmatchedCount
      // Unmatched is an admin screen, so only an admin is pointed at it; a
      // member being told about forty unmatched folders can do nothing with it.
      return (
        <p>
          {initialConfig.isAdmin && unmatched > 0
            ? t(
                'A scan finished without matching anything. {count} folders are waiting in Unmatched.',
                { count: unmatched },
              )
            : t('A scan finished without matching anything.')}
        </p>
      )
    }
    return <p>{t('No games found in your libraries.')}</p>
  }

  return <p>{t('No games match the current filters.')}</p>
}

/** Same keys, same values: a URL read that changes nothing keeps the filter object. */
function sameFilters(a: Record<string, unknown>, b: Record<string, unknown>) {
  const keys = Object.keys(a)
  return keys.length === Object.keys(b).length && keys.every((key) => a[key] === b[key])
}

export function LibraryApp({ initialConfig }: LooseProps = {}) {
  const viewer = useViewer()
  const shellConfig = useShellConfig()
  const t = useMemo(() => createTranslator(initialConfig.locale), [initialConfig.locale])
  const canBatchRefreshImages = Boolean(
    viewer.isLibrarian || viewer.isAdmin || initialConfig.isAdmin,
  )
  const useNewChrome = usesNewChrome(shellConfig)
  const filtersPanelId = useId()
  // The rail is rendered by the shell, not by this tree, so the slot only
  // exists after mount. Resolving it in state (rather than a ref read during
  // render) makes the first paint correct instead of one frame late.
  const [railSlot, setRailSlot] = useState<any>(null)
  useEffect(() => {
    setRailSlot(document.getElementById('od-rail-slot'))
  }, [])
  const [searchParams, setSearchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(initialConfig.perPage)
  const [layout, setLayout] = useCatalogLayout()
  const defaultFilters = {
    sort_by: initialConfig.defaultSort,
    sort_order: initialConfig.defaultSortOrder,
  }
  const [filters, setFilters] = useState(() =>
    cleanFilters({
      ...defaultFilters,
      ...initialConfig.currentFilters,
      ...readLibraryFilters(),
      ...filtersFromSearchParams(searchParams),
    }),
  )
  const [result, setResult] = useState<BrowseResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<any>(null)
  const [retryCount, setRetryCount] = useState(0)
  const { selectedIds, clearSelection, selectPage, handleSelectionToggle } =
    useLibrarySelection(result)
  const {
    favoriteByUuid,
    wishlistPendingIds,
    selectionBusy,
    wishlistAvailable,
    playStatusAvailable,
    refreshImagesAvailable,
    runBatchFavorite,
    runBatchFreshness,
    runBatchWishlist,
    runBatchPlayStatus,
    runBatchRefreshImages,
  } = useLibraryBatchActions({ result, setResult, selectedIds, canBatchRefreshImages, t })
  const pages = Math.max(result?.pages ?? 1, 1)

  useEffect(() => {
    const fromUrl = filtersFromSearchParams(searchParams)
    if (!searchParamsHaveLibraryFilters(searchParams)) {
      return
    }
    setFilters((current) => {
      const same =
        current.library_platform === fromUrl.library_platform &&
        current.play_mode === fromUrl.play_mode &&
        current.genre === fromUrl.genre &&
        current.theme === fromUrl.theme &&
        current.game_mode === fromUrl.game_mode &&
        current.player_perspective === fromUrl.player_perspective &&
        current.item_kind === fromUrl.item_kind &&
        current.name === fromUrl.name &&
        current.filter_tree === fromUrl.filter_tree &&
        OWNERSHIP_FILTER_KEYS.every((key) => current[key] === fromUrl[key]) &&
        BADGE_FILTER_PARAMS.every((param) => current[param] === fromUrl[param])
      if (same) {
        return current
      }
      const next = cleanFilters({ ...current, ...fromUrl })
      if (sameFilters(next, current)) {
        // The URL was written from these filters (syncOwnershipUrl); keeping
        // the same object avoids a second browse request for the same view.
        return current
      }
      writeLibraryFilters(next)
      return next
    })
    setPage(1)
  }, [searchParams])

  useEffect(() => {
    if (filters.library_platform) {
      applyPlatformSkin(filters.library_platform)
    } else {
      clearPlatformSkin()
    }
    return () => {
      clearPlatformSkin()
    }
  }, [filters.library_platform])

  useEffect(() => {
    const controller = new AbortController()
    let active = true

    setLoading(true)
    setError(null)
    fetchBrowseGames(
      {
        ...filters,
        page,
        per_page: perPage,
      },
      { signal: controller.signal },
    )
      .then((nextResult) => {
        if (active) {
          setResult(nextResult)
          setLoading(false)
        }
      })
      .catch((requestError: any) => {
        if (active && requestError.name !== 'AbortError') {
          setError(requestError)
          setLoading(false)
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [filters, page, perPage, retryCount])

  useEffect(() => {
    function onKeyDown(event: any) {
      if (event.key !== 'Escape') {
        return
      }
      if (selectedIds.size > 0) {
        clearSelection()
        return
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [selectedIds.size, clearSelection])

  const retry = () => {
    setRetryCount((count) => count + 1)
  }

  /**
   * Store / ownership filters are mirrored into the URL (LIB-02) so the view
   * can be linked. Other filter params already in the URL follow the applied
   * filters, so the URL read below cannot bring back a value the member changed.
   */
  const syncOwnershipUrl = (nextFilters: Record<string, string | undefined>) => {
    const next = withLibraryParams(searchParams, nextFilters)
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true })
    }
  }

  const applyFilters = (nextFilters: any) => {
    writeLibraryFilters(nextFilters)
    setPage(1)
    setFilters(nextFilters)
    clearSelection()
    syncOwnershipUrl(nextFilters)
  }

  /** Live title search — same filter apply, keep mobile LHN open while typing. */
  const applyLiveSearch = (nextFilters: any) => {
    writeLibraryFilters(nextFilters)
    setPage(1)
    setFilters(nextFilters)
    clearSelection()
    syncOwnershipUrl(nextFilters)
  }

  const clearFilters = () => {
    writeLibraryFilters(defaultFilters)
    setPage(1)
    setFilters(defaultFilters)
    clearSelection()
    if (searchParamsHaveLibraryFilters(searchParams)) {
      setSearchParams({}, { replace: true })
    }
  }

  const games = result?.games ?? []
  const showSkeleton = loading && !result
  const showRefreshing = loading && Boolean(result)
  const hidePlatformChip = Boolean(filters.library_platform)

  const selectedFavoriteMode = useMemo(() => {
    if (!selectedIds.size) return 'add'
    for (const uuid of selectedIds) {
      if (!favoriteByUuid[uuid]) return 'add'
    }
    return 'remove'
  }, [favoriteByUuid, selectedIds])
  const selectedWishlistMode = useMemo(() => {
    if (!selectedIds.size) return 'add'
    for (const uuid of selectedIds) {
      if (!wishlistPendingIds.has(uuid)) return 'add'
    }
    return 'remove'
  }, [selectedIds, wishlistPendingIds])

  const gridProps = {
    games,
    showPlayStatus: initialConfig.showPlayStatus,
    isAdmin: initialConfig.isAdmin,
    enableDeleteOnDisk: initialConfig.enableDeleteOnDisk,
    hidePlatformChip,
    selectionEnabled: true,
    selectedIds,
    onSelectionToggle: handleSelectionToggle,
    // Filtered to a system, a grouped tile names *that* system rather than the
    // newest one the title exists on — you are looking at that copy.
    activePlatform: filters.library_platform || '',
    layout,
    filters,
  }

  /* Grid does not page.
     Its shelves are genres, each fetching its own covers, so there is no
     "next 50" to walk — the pager offered 138 pages of genre headings that
     never added up to a genre. Tile and Rows still page; See all on a shelf
     hands the genre to Tile, which is the layout built for a long list. */
  const showPager = layout !== 'grid'

  let content
  if (error && !result) {
    content = (
      <PageStatus
        error={error}
        errorMessage={t('Unable to load games.')}
        onRetry={retry}
        retryLabel={t('Retry')}
      />
    )
  } else if (showSkeleton) {
    content = (
      <>
        <GameGridSkeleton count={perPage} layout={layout} />
        {showPager ? (
          <PaginationBar
            page={page}
            pages={1}
            perPage={perPage}
            onPageChange={(nextPage: any) => {
              clearSelection()
              setPage(nextPage)
            }}
            onPerPageChange={(nextPerPage: any) => {
              clearSelection()
              setPage(1)
              setPerPage(nextPerPage)
            }}
            t={t}
          />
        ) : null}
      </>
    )
  } else {
    content = (
      <>
        {error && (
          <PageStatus
            error={error}
            errorMessage={t('Unable to refresh games.')}
            onRetry={retry}
            retryLabel={t('Retry')}
          />
        )}
        {/* New chrome mounts selection in the top bar (replaces All/Games/View). */}
        {useNewChrome ? null : (
          <LibrarySelectionBar
            count={selectedIds.size}
            busy={selectionBusy}
            wishlistAvailable={wishlistAvailable}
            playStatusAvailable={playStatusAvailable}
            refreshImagesAvailable={refreshImagesAvailable}
            favoriteMode={selectedFavoriteMode}
            wishlistMode={selectedWishlistMode}
            onFavorite={() => void runBatchFavorite(true)}
            onUnfavorite={() => void runBatchFavorite(false)}
            onRefreshFreshness={() => void runBatchFreshness()}
            onRefreshImages={canBatchRefreshImages ? () => void runBatchRefreshImages() : undefined}
            onWishlist={() => void runBatchWishlist(false)}
            onWishlistRemove={() => void runBatchWishlist(true)}
            onPlayStatus={(status: any) => void runBatchPlayStatus(status)}
            onSelectPage={selectPage}
            onClear={clearSelection}
            t={t}
          />
        )}
        <StoreSetupPrompt t={t} />
        <div className={showRefreshing ? 'library-grid-loading' : undefined}>
          {games.length === 0 ? (
            <>
              <GameGrid {...gridProps} />
              <EmptyState initialConfig={initialConfig} t={t} />
            </>
          ) : (
            <GameGrid {...gridProps} />
          )}
        </div>
        {showPager ? (
          <PaginationBar
            page={page}
            pages={pages}
            perPage={perPage}
            onPageChange={(nextPage: any) => {
              clearSelection()
              setPage(nextPage)
            }}
            onPerPageChange={(nextPerPage: any) => {
              clearSelection()
              setPage(1)
              setPerPage(nextPerPage)
            }}
            t={t}
          />
        ) : null}
      </>
    )
  }

  // The label already rides along on the game rows, so the backdrop needs no
  // extra fetch and no 70-entry name table to stay in step with the enum.
  const selectedSystemLabel =
    (result?.games ?? []).find((game: any) => game.library_platform === filters.library_platform)
      ?.library_platform_label ||
    filters.library_platform ||
    ''

  // Kind becomes the segmented control. A URL may still carry several kinds —
  // that keeps working, it just lights no segment, which is honest: the
  // segmented control cannot represent "two of these at once".
  const activeKinds = parseItemKindFilter(filters.item_kind)
  const activeView = activeKinds.length === 1 ? activeKinds[0] : ''
  const kindViews = [
    { id: '', label: t('All') },
    ...ITEM_KIND_FILTER_CHIPS.map((chip) => ({ id: chip.kind, label: t(chip.label) })),
  ]

  function selectKindView(kind: any) {
    applyFilters(cleanFilters({ ...filters, item_kind: kind || '' }))
  }

  // Everything narrowing the grid that is *hidden* while the popover is shut.
  // Excluded: item_kind (the segmented control shows it in the open) and the
  // sort keys, which always carry a value from user preferences and are not
  // narrowing anything. Counting those showed "Filters 2" on an untouched
  // library, which is worse than no badge — it sends people hunting for a
  // filter they never set.
  // store_match only qualifies the store filter; counting it would make one
  // ownership choice read as two filters.
  const NOT_A_FILTER = new Set(['item_kind', 'sort_by', 'sort_order', 'store_match'])
  const activeFilterCount = Object.entries(cleanFilters(filters)).filter(
    ([key]) => !NOT_A_FILTER.has(key),
  ).length

  const selecting = selectedIds.size > 0
  const selectionBar = (
    <LibrarySelectionBar
      count={selectedIds.size}
      busy={selectionBusy}
      wishlistAvailable={wishlistAvailable}
      playStatusAvailable={playStatusAvailable}
      refreshImagesAvailable={refreshImagesAvailable}
      favoriteMode={selectedFavoriteMode}
      wishlistMode={selectedWishlistMode}
      onFavorite={() => void runBatchFavorite(true)}
      onUnfavorite={() => void runBatchFavorite(false)}
      onRefreshFreshness={() => void runBatchFreshness()}
      onRefreshImages={canBatchRefreshImages ? () => void runBatchRefreshImages() : undefined}
      onWishlist={() => void runBatchWishlist(false)}
      onWishlistRemove={() => void runBatchWishlist(true)}
      onPlayStatus={(status: any) => void runBatchPlayStatus(status)}
      onSelectPage={selectPage}
      onClear={clearSelection}
      t={t}
      inTopBar={useNewChrome}
    />
  )

  const filterBar = (
    <div className="library-filters-stack">
      <FilterBar
        filters={filters}
        onApply={applyFilters}
        onLiveSearch={applyLiveSearch}
        onClear={clearFilters}
        t={t}
      />
    </div>
  )

  if (useNewChrome) {
    return (
      <>
        <SystemBackdrop platform={filters.library_platform} label={selectedSystemLabel} />
        <ContextBar
          /* While selecting, the kind / View strip is unused — put the fused
             selection actions in the centre instead (Filters stay). */
          views={selecting ? undefined : kindViews}
          activeView={selecting ? undefined : activeView}
          onSelectView={selecting ? undefined : selectKindView}
          filterCount={activeFilterCount}
          filters={() => (
            <div className="library-filters-stack">
              <FilterBar
                filters={filters}
                onApply={applyFilters}
                onLiveSearch={applyLiveSearch}
                onClear={clearFilters}
                t={t}
                hideKind
              />
            </div>
          )}
          summary={
            selecting
              ? null
              : typeof result?.total === 'number'
                ? `${result.total.toLocaleString()} ${t('titles')}`
                : null
          }
          t={t}
          viewUnfurl={
            selecting
              ? null
              : {
                  views: CATALOG_LAYOUTS.map((view) => ({
                    ...view,
                    label: t(view.label),
                  })),
                  active: layout,
                  onSelect: setLayout,
                  triggerLabel: t('View'),
                }
          }
          actions={selecting ? selectionBar : null}
        />
        {/* No aside, no collapse rail, no page header — the grid gets the
            whole width, which is the visible payoff of the refresh. */}
        <div className="library-layout is-chrome-v2">
          <div className="library-layout__main">{content}</div>
        </div>
      </>
    )
  }

  return (
    <>
      <SystemBackdrop platform={filters.library_platform} label={selectedSystemLabel} />
      <div className="library-layout">
        {/* Filters render into the rail (GT-B4) — see #od-rail-slot in SideRail.
          They used to be a 17.5rem sticky aside sitting immediately right of
          the rail: two left-hand panels, which is what read as broken, plus a
          collapse tab that clipped itself against the top of the column.

          A portal rather than props or lifted state: every filter handler stays
          here, only the markup moves, and the shell never has to know what a
          filter is. When the rail is absent (Big Picture, tests) it falls back
          to rendering in place rather than vanishing. */}
        {railSlot ? (
          createPortal(filterBar, railSlot)
        ) : (
          <aside
            id={filtersPanelId}
            className="library-layout__filters"
            aria-label={t('Library filters')}
          >
            {filterBar}
          </aside>
        )}

        <div className="library-layout__main">{content}</div>
      </div>
    </>
  )
}
