import { useId, useMemo, useState, type Key, type ReactNode } from 'react'
import './DataTable.css'
import { PM_IGNORE } from './formIgnore.js'

/* Loose by design (PR-4 e house style): admin rows come off untyped JSON
 * helpers, so a row is `any` and a column carries optional render/value fns. */
export interface DataTableColumn {
  key: string
  label?: ReactNode
  sortable?: boolean
  filterable?: boolean
  align?: string
  render?: (row: any) => ReactNode
  value?: (row: any) => unknown
}

export interface DataTableProps {
  columns: DataTableColumn[]
  rows: any[]
  getRowKey: (row: any, index?: number) => Key
  emptyMessage?: string
  initialSort?: { key: string; dir: 'asc' | 'desc' } | null
  dense?: boolean
  caption?: ReactNode
  /** Name/focus entry point for tables that need a keyboard-scrollable region. */
  scrollLabel?: string
  toolbar?: boolean
  columnFilters?: boolean
  showCount?: boolean
}

/**
 * Sortable + filterable admin table (UX-C8).
 *
 * Every admin table was hand-rolled, so sorting and filtering existed on some
 * and not others with no consistent behaviour. This is the one implementation
 * they should all share.
 *
 * columns: [{ key, label, sortable?, filterable?, render?, value?, align? }]
 *   - `value(row)` supplies the sort/filter key when the cell renders markup;
 *     without it we fall back to `row[key]`, so a column that renders a badge
 *     still sorts on the underlying value rather than on "[object Object]".
 *
 * `toolbar={false}` drops the filter box and row count, keeping the shared
 * header, sorting and empty state. Ops panels are the case it exists for: a
 * filter box above three rows of companion kinds is more chrome than content,
 * and without this the only way to avoid it was to hand-roll the table — which
 * is how these panels came to disagree with every other table in the first place.
 *
 * `columnFilters` puts a typeahead search beside each filterable column title
 * (AND across columns). Use with `toolbar={false}` when the global box would
 * be redundant.
 */
export function DataTable({
  columns,
  rows,
  getRowKey,
  emptyMessage = 'Nothing to show.',
  initialSort = null,
  dense = false,
  caption,
  scrollLabel,
  toolbar = true,
  columnFilters = false,
  showCount,
}: DataTableProps) {
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(initialSort) // { key, dir: 'asc' | 'desc' }
  const [query, setQuery] = useState('')
  const [columnQuery, setColumnQuery] = useState<Record<string, string>>({})
  const listId = useId()

  const cellValue = (column: DataTableColumn, row: any): unknown => {
    if (typeof column.value === 'function') {
      return column.value(row)
    }
    return row?.[column.key]
  }

  const filterable = columns.filter((c) => c.filterable !== false)
  const countVisible = showCount ?? Boolean(toolbar || columnFilters)

  const suggestionsByKey = useMemo<Record<string, string[]>>(() => {
    if (!columnFilters) return {}
    const out: Record<string, string[]> = {}
    for (const column of filterable) {
      const seen = new Set<string>()
      const values: string[] = []
      for (const row of rows) {
        const raw = cellValue(column, row)
        if (raw == null || raw === '') continue
        const text = String(raw)
        const key = text.toLowerCase()
        if (seen.has(key)) continue
        seen.add(key)
        values.push(text)
        if (values.length >= 80) break
      }
      out[column.key] = values
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, columnFilters, columns])

  const filtered = useMemo(() => {
    let next = rows

    if (columnFilters) {
      next = next.filter((row) =>
        filterable.every((column) => {
          const needle = String(columnQuery[column.key] || '')
            .trim()
            .toLowerCase()
          if (!needle) return true
          const raw = cellValue(column, row)
          return raw != null && String(raw).toLowerCase().includes(needle)
        }),
      )
    }

    const needle = query.trim().toLowerCase()
    if (!needle) {
      return next
    }
    return next.filter((row) =>
      filterable.some((column) => {
        const raw = cellValue(column, row)
        return raw != null && String(raw).toLowerCase().includes(needle)
      }),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, query, columnQuery, columnFilters, columns])

  const sorted = useMemo(() => {
    if (!sort?.key) {
      return filtered
    }
    const column = columns.find((c) => c.key === sort.key)
    if (!column) {
      return filtered
    }
    const factor = sort.dir === 'desc' ? -1 : 1
    // Copy first — sorting the caller's array in place is a nasty surprise.
    return [...filtered].sort((a, b) => {
      const av = cellValue(column, a)
      const bv = cellValue(column, b)

      // Absent values sort last in both directions; "missing" is not "smallest".
      const aEmpty = av == null || av === ''
      const bEmpty = bv == null || bv === ''
      if (aEmpty && bEmpty) return 0
      if (aEmpty) return 1
      if (bEmpty) return -1

      if (typeof av === 'number' && typeof bv === 'number') {
        return (av - bv) * factor
      }
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * factor
    })
  }, [filtered, sort, columns])

  const toggleSort = (key: string) => {
    setSort((current) => {
      if (current?.key !== key) {
        return { key, dir: 'asc' }
      }
      if (current.dir === 'asc') {
        return { key, dir: 'desc' }
      }
      return null // third click clears, so a table can go back to source order
    })
  }

  const hasActiveColumnFilter = filterable.some((column) =>
    String(columnQuery[column.key] || '').trim(),
  )
  const filterActive = Boolean(query.trim()) || hasActiveColumnFilter

  const renderFilter = (column: DataTableColumn) => {
    if (!columnFilters || column.filterable === false) return null
    const label = typeof column.label === 'string' ? column.label : column.key
    const options = suggestionsByKey[column.key] || []
    const datalistId = `${listId}-${column.key}`
    return (
      <>
        <input
          type="search"
          className="od-table__col-filter"
          value={columnQuery[column.key] || ''}
          list={options.length ? datalistId : undefined}
          autoComplete="off"
          {...PM_IGNORE}
          onChange={(event) =>
            setColumnQuery((prev) => ({
              ...prev,
              [column.key]: event.target.value,
            }))
          }
          placeholder="Filter…"
          aria-label={`Filter ${label}`}
        />
        {options.length ? (
          <datalist id={datalistId}>
            {options.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        ) : null}
      </>
    )
  }

  return (
    <div className={`od-table-wrap${dense ? ' od-table-wrap--dense' : ''}`}>
      {toolbar ? (
        <div className="od-table-toolbar">
          <label className="od-table-filter">
            <span className="od-table-filter__label">Filter</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Type to filter…"
              aria-label="Filter table rows"
              {...PM_IGNORE}
            />
          </label>
          {countVisible ? (
            <span className="od-table-count" aria-live="polite">
              {filterActive && filtered.length !== rows.length
                ? `${filtered.length} of ${rows.length}`
                : `${rows.length} row${rows.length === 1 ? '' : 's'}`}
            </span>
          ) : null}
        </div>
      ) : null}

      <div
        className="od-table-scroll"
        role={scrollLabel ? 'region' : undefined}
        aria-label={scrollLabel || undefined}
        tabIndex={scrollLabel ? 0 : undefined}
      >
        <table className="od-table">
          {caption ? <caption className="od-table__caption">{caption}</caption> : null}
          <thead>
            <tr>
              {columns.map((column) => {
                const active = sort?.key === column.key
                const ariaSort = !active ? 'none' : sort.dir === 'asc' ? 'ascending' : 'descending'
                const canFilter = columnFilters && column.filterable !== false
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={column.sortable === false ? undefined : ariaSort}
                    className={column.align ? `is-${column.align}` : undefined}
                  >
                    <div className={`od-table__head${canFilter ? ' has-filter' : ''}`}>
                      {column.sortable === false ? (
                        <span className="od-table__title">{column.label}</span>
                      ) : (
                        <button
                          type="button"
                          className={`od-table__sort${active ? ' is-active' : ''}`}
                          onClick={() => toggleSort(column.key)}
                        >
                          {column.label}
                          <span className="od-table__sort-mark" aria-hidden="true">
                            {active ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}
                          </span>
                        </button>
                      )}
                      {renderFilter(column)}
                    </div>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="od-table__empty">
                  {filterActive ? `No rows match “${query.trim() || 'filters'}”.` : emptyMessage}
                </td>
              </tr>
            ) : (
              sorted.map((row, index) => (
                <tr key={getRowKey ? getRowKey(row, index) : index}>
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={column.align ? `is-${column.align}` : undefined}
                    >
                      {column.render ? column.render(row) : (cellValue(column, row) as ReactNode)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {!toolbar && countVisible ? (
        <span className="od-table-count" aria-live="polite">
          {filterActive && filtered.length !== rows.length
            ? `${filtered.length} of ${rows.length}`
            : `${rows.length} row${rows.length === 1 ? '' : 's'}`}
        </span>
      ) : null}
    </div>
  )
}
