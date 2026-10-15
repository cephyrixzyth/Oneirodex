import { FilterChipGroup } from '@oneirodex/ui'

/* FilterPanel moved out of TrailersPage (v11 cycle, H-D.2) — unchanged. */

export function FilterPanel({
  options,
  optionsError,
  filters,
  onChange,
  onClear,
  onApply,
}: LooseProps) {
  const dateRange = options?.date_range || {}

  /* Same shape as Library's FilterBar: Apply/Clear fused at the top, fields in
     `.library-filters__body`, no nested box. The popover frame is the only
     surface when this opens under new chrome (chromeless + bare panel). */
  return (
    <form
      className="container-filtersandsort library-filters od-trailers-filters"
      onSubmit={(event) => {
        event.preventDefault()
        onApply()
      }}
    >
      <div className="library-filters__actions">
        <div className="od-cbtn-group od-cbtn-group--fill">
          <button type="submit" className="od-cbtn od-cbtn--primary">
            Apply
          </button>
          <button type="button" className="od-cbtn" onClick={onClear}>
            Clear
          </button>
        </div>
      </div>

      <div className="library-filters__body">
        {optionsError ? (
          <p className="od-trailers__filter-error">Filter options are unavailable right now.</p>
        ) : null}

        <label htmlFor="od-trailers-library">
          Library
          <select
            id="od-trailers-library"
            className="form-control"
            value={filters.library}
            onChange={(event) => onChange({ library: event.target.value })}
          >
            <option value="">All Libraries</option>
            {(options?.libraries || []).map((library: any) => (
              <option key={library.uuid} value={library.uuid}>
                {library.name}
              </option>
            ))}
          </select>
        </label>

        <label htmlFor="od-trailers-date-from">
          Release year from
          <input
            id="od-trailers-date-from"
            className="form-control"
            type="number"
            min={dateRange.min_year || 1970}
            max={dateRange.max_year || 2030}
            placeholder={`e.g., ${dateRange.min_year || 1990}`}
            value={filters.dateFrom}
            onChange={(event) => onChange({ dateFrom: event.target.value })}
          />
        </label>

        <label htmlFor="od-trailers-date-to">
          Release year to
          <input
            id="od-trailers-date-to"
            className="form-control"
            type="number"
            min={dateRange.min_year || 1970}
            max={dateRange.max_year || 2030}
            placeholder={`e.g., ${dateRange.max_year || 2024}`}
            value={filters.dateTo}
            onChange={(event) => onChange({ dateTo: event.target.value })}
          />
        </label>

        <fieldset className="library-filters__multi-select">
          <legend>Genres</legend>
          <FilterChipGroup
            label="Genre options"
            options={(options?.genres || []).map((genre: any) => ({
              value: String(genre.id),
              label: genre.name,
            }))}
            value={filters.genres}
            onChange={(genres) => onChange({ genres })}
          />
        </fieldset>

        <fieldset className="library-filters__multi-select">
          <legend>Themes</legend>
          <FilterChipGroup
            label="Theme options"
            options={(options?.themes || []).map((theme: any) => ({
              value: String(theme.id),
              label: theme.name,
            }))}
            value={filters.themes}
            onChange={(themes) => onChange({ themes })}
          />
        </fieldset>
      </div>
    </form>
  )
}
