import { useEffect, useRef, useState } from 'react'
import { fetchFilterOptions } from '../api/filters'
import { PageStatus } from './PageStatus'
import { BADGE_FILTER_CHIPS, toggleBadgeFilter } from './BadgeFilterChips'
import {
  ITEM_KIND_FILTER_CHIPS,
  parseItemKindFilter,
  toggleItemKindFilter,
} from './ItemKindFilterChips'
import { SavedFilterPanel } from './filterBuilder/SavedFilterPanel'
import { OwnershipFilterControls } from './OwnershipFilterControls'
import type { FilterNode } from '../api/savedFilters'

const EMPTY_OPTIONS: Record<string, any[]> = {
  libraries: [],
  libraryPlatforms: [],
  igdbPlatforms: [],
  genres: [],
  themes: [],
  gameModes: [],
  playerPerspectives: [],
  ownershipStores: [],
}

const SELECTS = [
  ['library_uuid', 'Library', 'All Libraries', 'libraries', 'uuid', 'name'],
  ['library_platform', 'System / console', 'All systems', 'libraryPlatforms', 'value', 'name'],
  ['igdb_platform', 'Catalog platform', 'All catalog platforms', 'igdbPlatforms', 'name', 'name'],
  ['genre', 'Genre', 'All Genres', 'genres', 'name', 'name'],
  ['theme', 'Theme', 'All Themes', 'themes', 'name', 'name'],
  ['game_mode', 'Game mode', 'All Game Modes', 'gameModes', 'name', 'name'],
  [
    'player_perspective',
    'Player perspective',
    'All Perspectives',
    'playerPerspectives',
    'name',
    'name',
  ],
]

/** localStorage: '1' = LHN expanded (default), '0' = collapsed rail. */
export const FILTERS_VISIBLE_KEY = 'od.library.filtersVisible'
/** Debounce for type-to-search title filter (ms). */
export const LIBRARY_SEARCH_DEBOUNCE_MS = 300

export function readFiltersVisible() {
  try {
    const raw = window.localStorage?.getItem(FILTERS_VISIBLE_KEY)
    if (raw === '0' || raw === 'false') return false
    if (raw === '1' || raw === 'true') return true
  } catch {
    /* ignore */
  }
  return true
}

export function writeFiltersVisible(visible: any) {
  try {
    window.localStorage?.setItem(FILTERS_VISIBLE_KEY, visible ? '1' : '0')
  } catch {
    /* ignore */
  }
}

export function cleanFilters(filters: any) {
  return Object.fromEntries(
    Object.entries(filters).filter(([key, value]) => {
      if (value === '' || value === undefined || value === null) {
        return false
      }
      if (key === 'rating' && (value === 0 || value === '0')) {
        return false
      }
      if (key === 'name' && typeof value === 'string' && !value.trim()) {
        return false
      }
      return true
    }),
  )
}

function CollapseChevron({ collapsed }: LooseProps) {
  return (
    <svg
      className="library-filters-collapse__icon"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      {collapsed ? (
        <path
          fill="currentColor"
          d="M5.47 2.97a.75.75 0 0 1 1.06 0l4.5 4.5a.75.75 0 0 1 0 1.06l-4.5 4.5a.75.75 0 1 1-1.06-1.06L9.44 8 5.47 4.03a.75.75 0 0 1 0-1.06z"
        />
      ) : (
        <path
          fill="currentColor"
          d="M10.53 2.97a.75.75 0 0 0-1.06 0l-4.5 4.5a.75.75 0 0 0 0 1.06l4.5 4.5a.75.75 0 1 0 1.06-1.06L6.56 8l3.97-3.97a.75.75 0 0 0 0-1.06z"
        />
      )}
    </svg>
  )
}

/**
 * Slim arrow that collapses/expands the Library LHN so the game grid reflows.
 * Rendered by LibraryApp (layout owns width); kept next to FilterBar for a11y labels.
 */
export function LibraryFiltersCollapseToggle({
  collapsed,
  onToggle,
  controlsId,
  t = (key: any) => key,
}: LooseProps) {
  return (
    <button
      type="button"
      className="library-filters-collapse"
      aria-expanded={!collapsed}
      aria-controls={controlsId}
      title={collapsed ? t('Show filters') : t('Hide filters')}
      onClick={onToggle}
    >
      <CollapseChevron collapsed={collapsed} />
      <span className="visually-hidden">{collapsed ? t('Show filters') : t('Hide filters')}</span>
    </button>
  )
}

export function FilterBar({
  filters,
  onApply,
  onClear,
  onLiveSearch,
  t = (key: any) => key,
  // UIR-2: the two-bar chrome promotes Kind to a segmented control in the
  // context bar. Rendering it here as well would give one filter two controls,
  // so the panel yields ownership rather than duplicating it.
  hideKind = false,
}: LooseProps) {
  const [draft, setDraft] = useState(filters)
  const [options, setOptions] = useState(EMPTY_OPTIONS)
  const [loadError, setLoadError] = useState(false)
  const searchTimerRef = useRef<any>(null)
  const draftRef = useRef(draft)
  draftRef.current = draft

  useEffect(() => {
    setDraft(filters)
  }, [filters])

  useEffect(() => {
    const controller = new AbortController()
    fetchFilterOptions({ signal: controller.signal })
      .then((next) => setOptions({ ...EMPTY_OPTIONS, ...next } as Record<string, any[]>))
      .catch((error: any) => {
        if (error.name !== 'AbortError') {
          setLoadError(true)
        }
      })

    return () => controller.abort()
  }, [])

  useEffect(
    () => () => {
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current)
      }
    },
    [],
  )

  const activeTree: FilterNode | null = (() => {
    const raw = filters.filter_tree
    if (typeof raw !== 'string' || !raw.trim()) return null
    try {
      return JSON.parse(raw) as FilterNode
    } catch {
      // A filter we cannot read is not one we should pretend is applied.
      return null
    }
  })()

  const applyTree = (tree: FilterNode | null) => {
    const next = { ...filters }
    if (tree) {
      next.filter_tree = JSON.stringify(tree)
    } else {
      delete next.filter_tree
    }
    onApply(cleanFilters(next))
  }

  const update = (event: any) => {
    setDraft((current: any) => ({
      ...current,
      [event.target.name]: event.target.value,
    }))
  }

  const applyLiveName = (nameValue: any) => {
    const next = cleanFilters({
      ...draftRef.current,
      name: typeof nameValue === 'string' ? nameValue.trim() : nameValue,
    })
    if (onLiveSearch) {
      onLiveSearch(next)
    } else {
      onApply(next)
    }
  }

  const onSearchChange = (event: any) => {
    const value = event.target.value
    setDraft((current: any) => ({
      ...current,
      name: value,
    }))
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current)
    }
    searchTimerRef.current = setTimeout(() => {
      applyLiveName(value)
    }, LIBRARY_SEARCH_DEBOUNCE_MS)
  }

  const submit = (event: any) => {
    event.preventDefault()
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current)
      searchTimerRef.current = null
    }
    onApply(cleanFilters(draft))
  }

  const clear = () => {
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current)
      searchTimerRef.current = null
    }
    setDraft({})
    onClear()
  }

  const applyBadgeToggle = (next: any) => {
    setDraft(next)
    onApply(next)
  }

  const selects = SELECTS.map(([name, label, emptyLabel, source, valueField, textField]) => [
    name,
    t(label),
    t(emptyLabel),
    source,
    valueField,
    textField,
  ])

  return (
    <form className="container-filtersandsort library-filters" onSubmit={submit}>
      {/* Apply / Clear lead the panel as one control.
          At the foot they were detached buttons below every select and chip —
          so on a tall popover you scrolled past everything you had just set in
          order to commit it. They are one decision about one panel, so they
          read as one segmented control. Dismiss is click-outside / Escape /
          the Filters trigger — a third Done in this cluster was redundant. */}
      <div className="library-filters__actions">
        <div className="od-cbtn-group od-cbtn-group--fill">
          <button className="od-cbtn od-cbtn--primary" type="submit">
            {t('Apply')}
          </button>
          <button className="od-cbtn" type="button" onClick={clear}>
            {t('Clear')}
          </button>
        </div>

        {/* Signals sit under Apply/Clear as one compact fused row — half the
            control height so the commit cluster stays the loudest thing at the top. */}
        <fieldset className="library-filters__signals library-filters__signals--bar">
          <legend className="visually-hidden">{t('Signals')}</legend>
          <div
            className="od-cbtn-group od-cbtn-group--fill"
            role="group"
            aria-label={t('Badge filters')}
          >
            {BADGE_FILTER_CHIPS.map((chip) => {
              const active = (filters[chip.param] ?? draft[chip.param]) === '1'
              return (
                <button
                  key={chip.param}
                  type="button"
                  className={`od-cbtn${active ? ' is-on' : ''}`}
                  aria-pressed={active}
                  title={t(chip.title)}
                  onClick={() =>
                    toggleBadgeFilter(filters, chip.param, applyBadgeToggle, cleanFilters)
                  }
                >
                  {t(chip.label)}
                </button>
              )
            })}
          </div>
        </fieldset>

        {/* INSP-3. The chip row above can only ever mean *and*; this is where a
            member says "or" and keeps the result under a name. The tree rides
            as one more filter value (`filter_tree`), so browse needs no new
            plumbing, and applying one does not clear the chips -- someone who
            built a tree and then taps a chip means both. */}
        <SavedFilterPanel activeTree={activeTree} onApply={applyTree} t={t} />
      </div>

      <div className="library-filters__toolbar">
        <label className="library-filters__search">
          <span className="visually-hidden">{t('Search library')}</span>
          <input
            type="search"
            className="form-control library-filters__search-input"
            name="name"
            value={draft.name ?? ''}
            placeholder={t('Search by title')}
            aria-label={t('Search library by title')}
            autoComplete="off"
            onChange={onSearchChange}
          />
        </label>
      </div>

      <div id="library-filters-body" className="library-filters__body">
        {loadError ? <PageStatus error errorMessage={t('Unable to load filter options.')} /> : null}
        {selects.map(([name, label, emptyLabel, source, valueField, textField]) => (
          <label key={name}>
            {label}
            <select
              className="form-control"
              name={name}
              value={draft[name] ?? ''}
              onChange={update}
            >
              <option value="">{emptyLabel}</option>
              {options[source].map((option: any) => (
                <option key={option.id ?? option[valueField]} value={option[valueField]}>
                  {option[textField]}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label>
          {t('Companion')}
          <select
            className="form-control"
            name="installed_only"
            value={draft.installed_only ?? ''}
            onChange={update}
          >
            <option value="">{t('All games')}</option>
            <option value="1">{t('Companion installed')}</option>
          </select>
        </label>
        <label>
          {t('Play path')}
          <select
            className="form-control"
            name="play_mode"
            value={draft.play_mode ?? ''}
            onChange={update}
          >
            <option value="">{t('Any path')}</option>
            <option value="browser">{t('Browser')}</option>
            <option value="companion">{t('Companion')}</option>
            <option value="catalog">{t('Catalog')}</option>
          </select>
        </label>
        <label>
          {t('Sort by')}
          <select
            className="form-control"
            name="sort_by"
            value={draft.sort_by ?? 'name'}
            onChange={update}
          >
            <option value="name">{t('Name')}</option>
            <option value="rating">{t('Rating')}</option>
            <option value="first_release_date">{t('Date Released')}</option>
            <option value="date_identified">{t('Date Added')}</option>
            <option value="size">{t('Filesize')}</option>
          </select>
        </label>
        <label>
          {t('Sort order')}
          <select
            className="form-control"
            name="sort_order"
            value={draft.sort_order ?? 'asc'}
            onChange={update}
          >
            <option value="asc">{t('Ascending')}</option>
            <option value="desc">{t('Descending')}</option>
          </select>
        </label>

        {hideKind ? null : (
          <fieldset className="library-filters__signals">
            <legend>{t('Kind')}</legend>
            <div className="od-badge-filter-chips" role="group" aria-label={t('Kind filters')}>
              {ITEM_KIND_FILTER_CHIPS.map((chip) => {
                const active = parseItemKindFilter(filters.item_kind ?? draft.item_kind).includes(
                  chip.kind,
                )
                return (
                  <button
                    key={chip.kind}
                    type="button"
                    className={`od-badge-filter-chip${active ? ' is-active' : ''}`}
                    aria-pressed={active}
                    title={t(chip.title)}
                    onClick={() =>
                      toggleItemKindFilter(filters, chip.kind, applyBadgeToggle, cleanFilters)
                    }
                  >
                    {t(chip.label)}
                  </button>
                )
              })}
            </div>
          </fieldset>
        )}

        <OwnershipFilterControls
          filters={filters}
          stores={options.ownershipStores || []}
          onApply={applyBadgeToggle}
          clean={cleanFilters}
          t={t}
        />

        <label className="library-filters__rating">
          <span className="library-filters__rating-head">
            <span>{t('Rating')}</span>
            <span className="library-filters__rating-value" aria-live="polite">
              {draft.rating ?? '0'}
            </span>
          </span>
          <input
            type="range"
            className="form-control-range rating-slider"
            name="rating"
            min="0"
            max="100"
            value={draft.rating ?? '0'}
            onChange={update}
            aria-valuetext={String(draft.rating ?? '0')}
          />
        </label>
      </div>
    </form>
  )
}
