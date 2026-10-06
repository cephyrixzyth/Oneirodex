import { useCallback, useEffect, useMemo, useState } from 'react'
import { getJson, postJsonResult } from '../api/adminApi'
import { DataTable, type DataTableColumn } from './DataTable'
import { gameCountHeat } from './gameCountHeat'
import { ScanConflictModal } from './ScanConflictModal'
import { useLibraryScan } from '../hooks/useLibraryScan'
import { showToast } from '../utils/toast'
import {
  BATCH_EDIT_URL,
  BATCH_SCAN_URL,
  CATALOG_REFRESH_FLAG,
  DEFAULT_LIBRARY_IMAGE,
  groupLabel,
  libraryThumb,
} from './libraries/librariesModel'
import type { LibraryRow, PlatformSummary } from './libraries/librariesModel'
import { LibrariesTrailSummary, kickCatalogRefresh } from './libraries/LibrariesTrailSummary'
import { GroupDialog } from './libraries/GroupDialog'
import { CreateLibraryForm } from './CreateLibraryForm'
import './LibrariesPanel.css'

export function LibrariesPanel({ panelEl: _panelEl = null }: { panelEl?: Element | null }) {
  const [rows, setRows] = useState<LibraryRow[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [platformFilter, setPlatformFilter] = useState('')
  const [groupTargets, setGroupTargets] = useState<LibraryRow[] | null>(null)
  const [groupBusy, setGroupBusy] = useState(false)
  const { conflictOpen, busyKey, startScan, onConflictChoose, onConflictClose } = useLibraryScan()

  const reload = useCallback(() => {
    setError(null)
    return getJson('/api/get_libraries')
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((err) => {
        setError(err)
        setRows([])
      })
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    if (!rows?.length) return undefined
    void kickCatalogRefresh(rows).then(() => {
      /* After a first-wave IGDB refresh, reload once so DAT/IGDB totals replace estimates. */
      const flagged = (() => {
        try {
          return window.sessionStorage?.getItem(`${CATALOG_REFRESH_FLAG}:reloaded`)
        } catch {
          return '1'
        }
      })()
      if (flagged) return
      try {
        window.sessionStorage?.setItem(`${CATALOG_REFRESH_FLAG}:reloaded`, '1')
      } catch {
        /* ignore */
      }
      void reload()
    })
    return undefined
  }, [rows, reload])

  const toggleOne = useCallback((uuid: string, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(uuid)
      else next.delete(uuid)
      return next
    })
  }, [])

  const toggleAll = useCallback(
    (on: boolean) => {
      if (!rows) return
      setSelected(on ? new Set(rows.map((r) => r.uuid)) : new Set())
    },
    [rows],
  )

  const selectedList = useMemo(() => {
    if (!rows) return []
    return rows.filter((r) => selected.has(r.uuid))
  }, [rows, selected])

  const askDelete = useCallback((targets: { uuid: string; name: string }[]) => {
    if (typeof window.odLibrariesAskDelete === 'function') {
      window.odLibrariesAskDelete(targets)
      return
    }
    showToast('Delete confirm is unavailable on this page.', 'error')
  }, [])

  const openEdit = useCallback((targets: Array<{ uuid: string; name: string }>) => {
    if (!targets.length) return
    if (typeof window.odLibrariesOpenBatchEdit === 'function') {
      window.odLibrariesOpenBatchEdit(targets)
      return
    }
    showToast('Edit is unavailable on this page.', 'error')
  }, [])

  const openBatchEdit = useCallback(() => {
    openEdit(selectedList)
  }, [openEdit, selectedList])

  const batchScan = useCallback(async () => {
    if (!selectedList.length) return
    const { ok, data } = await postJsonResult(BATCH_SCAN_URL, {
      library_uuids: selectedList.map((r) => r.uuid),
      queue_policy: 'queue',
    })
    if (!ok) {
      showToast(data?.error || data?.message || 'Batch scan failed.', 'error')
      return
    }
    showToast(data?.message || `Queued scan for ${selectedList.length} libraries.`, 'success')
  }, [selectedList])

  const saveGroup = useCallback(
    async (name: string) => {
      if (!groupTargets?.length) return
      setGroupBusy(true)
      const { ok, data } = await postJsonResult(BATCH_EDIT_URL, {
        library_uuids: groupTargets.map((r) => r.uuid),
        group_name: name,
      })
      setGroupBusy(false)
      if (!ok) {
        showToast(data?.error || data?.message || 'Could not update group.', 'error')
        return
      }
      setGroupTargets(null)
      void reload()
    },
    [groupTargets, reload],
  )

  useEffect(() => {
    const onDeleted = () => {
      setSelected(new Set())
      void reload()
    }
    window.addEventListener('od-libraries-deleted', onDeleted)
    return () => window.removeEventListener('od-libraries-deleted', onDeleted)
  }, [reload])

  const anyGrouped = Boolean(rows?.some((lib) => groupLabel(lib)))
  const existingGroups = useMemo(() => {
    const seen = new Set<string>()
    const names: string[] = []
    for (const lib of rows || []) {
      const name = groupLabel(lib)
      if (!name || seen.has(name.toLowerCase())) continue
      seen.add(name.toLowerCase())
      names.push(name)
    }
    return names
  }, [rows])

  const visibleRows = useMemo(() => {
    if (!rows) return []
    const wanted = platformFilter.trim().toLowerCase()
    if (!wanted) return rows
    return rows.filter(
      (lib) =>
        String(lib.platform || '')
          .trim()
          .toLowerCase() === wanted,
    )
  }, [platformFilter, rows])

  const totalGames = useMemo(
    () => (rows || []).reduce((sum, lib) => sum + (Number(lib.game_count) || 0), 0),
    [rows],
  )

  const totalUnmatched = useMemo(
    () => (rows || []).reduce((sum, lib) => sum + (Number(lib.unmatched_count) || 0), 0),
    [rows],
  )

  const platforms = useMemo(() => {
    const byPlatform = new Map<string, PlatformSummary>()
    for (const lib of rows || []) {
      const platform = String(lib.platform || '').trim() || 'Unknown'
      const current = byPlatform.get(platform) || { platform, games: 0, unmatched: 0 }
      current.games += Number(lib.game_count) || 0
      current.unmatched += Number(lib.unmatched_count) || 0
      byPlatform.set(platform, current)
    }
    return [...byPlatform.values()].sort((a, b) =>
      a.platform.localeCompare(b.platform, undefined, { numeric: true }),
    )
  }, [rows])

  const actionButtons = useCallback(
    (lib: LibraryRow) => (
      <div
        className="od-cbtn-group od-libraries-actions"
        role="group"
        aria-label={`${lib.name} actions`}
      >
        <button
          type="button"
          className="od-cbtn"
          disabled={busyKey === lib.uuid}
          title={
            lib.last_scan_folder
              ? `Scan ${lib.last_scan_folder}`
              : 'No last scan folder — run Auto scan once first.'
          }
          onClick={() =>
            void startScan({
              key: lib.uuid,
              libraryUuid: lib.uuid,
              label: lib.name,
            })
          }
        >
          {busyKey === lib.uuid ? '…' : 'Scan'}
        </button>
        <button
          type="button"
          className="od-cbtn"
          onClick={() => openEdit([{ uuid: lib.uuid, name: lib.name }])}
        >
          Edit
        </button>
        <button
          type="button"
          className="od-cbtn od-cbtn--danger"
          onClick={() => askDelete([{ uuid: lib.uuid, name: lib.name }])}
        >
          Delete
        </button>
        <button type="button" className="od-cbtn" onClick={() => setGroupTargets([lib])}>
          Group
        </button>
      </div>
    ),
    [askDelete, busyKey, openEdit, startScan],
  )

  const columns = useMemo(() => {
    const cols: DataTableColumn[] = [
      {
        key: 'select',
        label: (
          <span className="od-libraries-select-all">
            <input
              type="checkbox"
              className="form-check-input"
              checked={Boolean(rows?.length && selected.size === rows.length)}
              ref={(el) => {
                if (el && rows) {
                  el.indeterminate = selected.size > 0 && selected.size < rows.length
                }
              }}
              onChange={(event) => toggleAll(event.target.checked)}
              aria-label="Select all libraries"
              title="Select all"
            />
          </span>
        ),
        sortable: false,
        filterable: false,
        render: (lib) => (
          <input
            type="checkbox"
            className="form-check-input od-library-row-check"
            checked={selected.has(lib.uuid)}
            data-library-uuid={lib.uuid}
            data-library-name={lib.name}
            aria-label={`Select ${lib.name}`}
            onChange={(event) => toggleOne(lib.uuid, event.target.checked)}
          />
        ),
      },
    ]
    if (anyGrouped) {
      cols.push({
        key: 'group_name',
        label: 'Group',
        value: (lib) => groupLabel(lib),
      })
    }
    cols.push(
      {
        key: 'name',
        label: 'Library',
        value: (lib) => lib.name || '',
        render: (lib) => (
          <span className="od-libraries-name">
            <img
              className="od-libraries-name__thumb"
              src={libraryThumb(lib.image_url)}
              alt=""
              width={30}
              height={30}
              loading="lazy"
              onError={(event) => {
                if (event.currentTarget.src.endsWith(DEFAULT_LIBRARY_IMAGE)) return
                event.currentTarget.src = DEFAULT_LIBRARY_IMAGE
              }}
            />
            <span className="od-libraries-name__text">{lib.name}</span>
          </span>
        ),
      },
      {
        key: 'platform',
        label: 'Platform',
        value: (lib) => lib.platform || '',
      },
      {
        key: 'game_count',
        label: 'Games',
        value: (lib) => Number(lib.game_count) || 0,
        render: (lib) => {
          const heat = gameCountHeat(lib.game_count, lib.platform_total)
          return (
            <span
              className="od-libraries-count"
              style={heat ? { color: heat.color } : undefined}
              title={heat?.title}
            >
              {Number(lib.game_count) || 0}
            </span>
          )
        },
      },
      {
        key: 'actions',
        label: 'Actions',
        sortable: false,
        filterable: false,
        render: actionButtons,
      },
    )
    return cols
  }, [actionButtons, anyGrouped, rows, selected, toggleAll, toggleOne])

  if (error && !rows) {
    return <p className="od-admin-lede od-error">Unable to load libraries.</p>
  }

  if (!rows) {
    return <p className="od-admin-lede">Loading libraries…</p>
  }

  const n = selectedList.length
  const libraryCount = rows.length

  return (
    <div className="od-libraries-react">
      <CreateLibraryForm onCreated={() => void reload()} />
      <LibrariesTrailSummary
        libraryCount={libraryCount}
        totalGames={totalGames}
        totalUnmatched={totalUnmatched}
        platforms={platforms}
        platformFilter={platformFilter}
        onPlatformFilter={setPlatformFilter}
      />
      {n > 0 ? (
        <div className="od-libraries-toolbar">
          <div className="od-libraries-batch-bar" id="odLibrariesBatchBarReact">
            <div className="od-libraries-batch-bar__inner">
              <span className="od-libraries-batch-bar__count">
                {n === 1 ? '1 selected' : `${n} selected`}
              </span>
              <button type="button" className="od-cbtn" onClick={() => void batchScan()}>
                Scan
              </button>
              <button type="button" className="od-cbtn" onClick={openBatchEdit}>
                Edit
              </button>
              <button
                type="button"
                className="od-cbtn od-cbtn--danger"
                onClick={() => askDelete(selectedList.map((r) => ({ uuid: r.uuid, name: r.name })))}
              >
                Delete
              </button>
              <button
                type="button"
                className="od-cbtn"
                onClick={() => setGroupTargets(selectedList)}
              >
                Group
              </button>
              <button type="button" className="od-cbtn" onClick={() => setSelected(new Set())}>
                Clear
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <DataTable
        rows={visibleRows}
        getRowKey={(lib) => lib.uuid}
        columns={columns}
        toolbar={false}
        columnFilters
        showCount={false}
        dense
        emptyMessage="No libraries yet. Create one above to start scanning."
        initialSort={{ key: 'name', dir: 'asc' }}
      />

      <ScanConflictModal
        open={conflictOpen}
        busy={Boolean(busyKey)}
        onChoose={onConflictChoose}
        onClose={onConflictClose}
      />

      {groupTargets ? (
        <GroupDialog
          key={groupTargets.map((lib) => lib.uuid).join(',')}
          targets={groupTargets}
          existingNames={existingGroups}
          busy={groupBusy}
          onClose={() => setGroupTargets(null)}
          onSave={(name) => void saveGroup(name)}
        />
      ) : null}
    </div>
  )
}
