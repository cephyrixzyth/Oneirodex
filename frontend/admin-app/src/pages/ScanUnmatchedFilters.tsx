import { Button } from '@oneirodex/ui'
import type { ScanUnmatchedModel } from './scanUnmatchedTypes'
const STATUS_FILTERS = [
  ['all', 'All'],
  ['Unmatched', 'Unmatched'],
  ['Duplicate', 'Duplicates'],
  ['Ignore', 'Ignored'],
  ['Pending', 'Pending'],
] as const
const WHY_FILTERS = [
  ['all', 'All'],
  ['same_path', 'Same path'],
  ['title_vs_folder', 'Title vs folder'],
  ['title_vs_library_name', 'Title vs library'],
  ['title_below_threshold', 'Below threshold'],
  ['cross_system', 'Cross-system'],
  ['region_mismatch', 'Region mismatch'],
] as const
type Props = Pick<
  ScanUnmatchedModel,
  | 'libraries'
  | 'loading'
  | 'status'
  | 'setStatus'
  | 'libraryUuid'
  | 'setLibraryUuid'
  | 'platform'
  | 'setPlatform'
  | 'region'
  | 'setRegion'
  | 'query'
  | 'setQuery'
  | 'why'
  | 'setWhy'
  | 'kind'
  | 'setKind'
  | 'layout'
  | 'setLayout'
  | 'triage'
  | 'setTriage'
  | 'pageSize'
  | 'setPageSize'
  | 'offset'
  | 'setOffset'
  | 'setSelectedIds'
  | 'selectedRows'
  | 'systems'
  | 'displayTotal'
  | 'changeFilter'
  | 'start'
  | 'end'
>
export function ScanUnmatchedFilters({
  libraries,
  loading,
  status,
  setStatus,
  libraryUuid,
  setLibraryUuid,
  platform,
  setPlatform,
  region,
  setRegion,
  query,
  setQuery,
  why,
  setWhy,
  kind,
  setKind,
  layout,
  setLayout,
  triage,
  setTriage,
  pageSize,
  setPageSize,
  offset,
  setOffset,
  setSelectedIds,
  selectedRows,
  systems,
  displayTotal,
  changeFilter,
  start,
  end,
}: Props) {
  return (
    <div className="od-scan-unmatched__filters">
      <div className="od-scan-unmatched__filter-group" role="group" aria-label="Status filter">
        {STATUS_FILTERS.map(([value, label]) => (
          <Button
            key={value}
            type="button"
            aria-pressed={status === value}
            className={`od-scan-unmatched__filter od-scan-unmatched__filter--status${status === value ? ' is-active' : ''}`}
            onClick={() => changeFilter(setStatus, value)}
          >
            {label}
          </Button>
        ))}
      </div>
      <label className="od-scan-unmatched__search">
        <span className="visually-hidden">Search unmatched folders</span>
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setSelectedIds(new Set())
            selectedRows.current.clear()
            setQuery(event.target.value)
            setOffset(0)
          }}
          placeholder="Search path, name, library, platform, or dupe title…"
        />
      </label>
      <div className="od-scan-unmatched__selects">
        <label>
          Library
          <select
            className="od-scan-unmatched__control"
            value={libraryUuid}
            onChange={(event) => changeFilter(setLibraryUuid, event.target.value)}
          >
            <option value="">All libraries</option>
            {libraries.map((row) => (
              <option key={row.uuid} value={row.uuid}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          System
          <select
            className="od-scan-unmatched__control"
            value={platform}
            onChange={(event) => changeFilter(setPlatform, event.target.value)}
          >
            <option value="">All systems</option>
            {systems.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Region
          <select
            className="od-scan-unmatched__control"
            value={region}
            onChange={(event) => changeFilter(setRegion, event.target.value)}
          >
            <option value="">All regions</option>
            {['USA', 'EUR', 'JPN', 'WORLD', 'OTHER'].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Page size
          <select
            className="od-scan-unmatched__control"
            aria-label="Rows per page"
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value) || 150)
              setOffset(0)
            }}
          >
            {[50, 150, 300, 500].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="od-scan-unmatched__chips">
        <div className="od-scan-unmatched__filter-group" role="group" aria-label="Layout filter">
          <strong>Layout</strong>
          {[
            ['all', 'All'],
            ['file-leaf', 'ROM files library'],
            ['folder-leaf', 'Folder library'],
          ].map(([value, label]) => (
            <Button
              key={value}
              type="button"
              aria-pressed={layout === value}
              className={`od-scan-unmatched__filter od-scan-unmatched__filter--chip${layout === value ? ' is-active' : ''}`}
              onClick={() => changeFilter(setLayout, value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <div className="od-scan-unmatched__filter-group" role="group" aria-label="Triage filter">
          <strong>Triage</strong>
          {[
            ['all', 'All'],
            ['platform-mismatch', 'Platform mismatch'],
            ['garbage', 'Garbage'],
          ].map(([value, label]) => (
            <Button
              key={value}
              type="button"
              aria-pressed={triage === value}
              className={`od-scan-unmatched__filter od-scan-unmatched__filter--chip${triage === value ? ' is-active' : ''}`}
              onClick={() => changeFilter(setTriage, value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <div className="od-scan-unmatched__filter-group" role="group" aria-label="Why filter">
          <strong>Why</strong>
          {WHY_FILTERS.map(([value, label]) => (
            <Button
              key={value}
              type="button"
              aria-pressed={why === value}
              className={`od-scan-unmatched__filter od-scan-unmatched__filter--chip${why === value ? ' is-active' : ''}`}
              onClick={() => changeFilter(setWhy, value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <div className="od-scan-unmatched__filter-group" role="group" aria-label="Kind filter">
          <strong>Kind</strong>
          {[
            ['all', 'All'],
            ['experience', 'Soft title'],
            ['emulator', 'Emulator'],
            ['tool', 'Utility'],
            ['none', 'No hint'],
          ].map(([value, label]) => (
            <Button
              key={value}
              type="button"
              aria-pressed={kind === value}
              className={`od-scan-unmatched__filter od-scan-unmatched__filter--chip${kind === value ? ' is-active' : ''}`}
              onClick={() => changeFilter(setKind, value)}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>
      <div className="od-scan-unmatched__pager">
        <span>
          Showing {start}–{end} of {displayTotal}
        </span>
        {displayTotal > pageSize ? (
          <div>
            <Button
              type="button"
              disabled={loading || offset <= 0}
              onClick={() => setOffset((value) => Math.max(0, value - pageSize))}
            >
              Previous
            </Button>
            <span>
              Page {displayTotal ? Math.floor(offset / pageSize) + 1 : 0} of{' '}
              {Math.max(1, Math.ceil(displayTotal / pageSize))}
            </span>
            <Button
              type="button"
              disabled={loading || offset + pageSize >= displayTotal}
              onClick={() => setOffset((value) => value + pageSize)}
            >
              Next
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
