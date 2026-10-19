import { useEffect, useMemo, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { csrfHeaders, getJson, postJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { OpenPathModal } from '../components/OpenPathModal'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  detectLeafType,
  detectPlatformMismatch,
  isGarbageScaffolding,
} from '../components/unmatchedTriage'
import './ScanUnmatchedPage.css'

type UnmatchedRow = {
  id: string | number
  folder_path?: string
  status?: string
  library_uuid?: string
  library_name?: string
  platform_name?: string
  rom_region?: string
  match_reason?: string
  match_score?: number | null
  suggested_kind?: string | null
  matched_game?: { name?: string; path?: string } | null
  folder_name?: string | null
  search_name?: string | null
  why_unmatched?: string | null
  unmatched_reason?: string | null
  bad_match_reason?: string | null
  suggested_candidate_name?: string | null
  is_bare_update_package?: boolean
  suggested_search_name?: string | null
  transforms?: Array<{ stage?: string; before?: string; after?: string; reason?: string }>
  stage_e_candidates?: Array<{ name?: string; source?: string; match_mode?: string }>
}

type LibraryOption = { uuid: string; name: string; platform?: string }
type BadMatchReason = { id: string; label: string }
type PageResult = { items?: UnmatchedRow[]; total?: number; count?: number }

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

export function ScanUnmatchedPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const routeState = location.state as { linkSuccess?: unknown } | null
  const [linkSuccess, setLinkSuccess] = useState(() =>
    typeof routeState?.linkSuccess === 'string' ? routeState.linkSuccess : '',
  )
  const [rows, setRows] = useState<UnmatchedRow[]>([])
  const [libraries, setLibraries] = useState<LibraryOption[]>([])
  const [badMatchReasons, setBadMatchReasons] = useState<BadMatchReason[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [status, setStatus] = useState('all')
  const [libraryUuid, setLibraryUuid] = useState('')
  const [platform, setPlatform] = useState('')
  const [region, setRegion] = useState('')
  const [query, setQuery] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [why, setWhy] = useState('all')
  const [kind, setKind] = useState('all')
  const [layout, setLayout] = useState('all')
  const [triage, setTriage] = useState('all')
  const [pageSize, setPageSize] = useState(150)
  const [offset, setOffset] = useState(0)
  const [pathModal, setPathModal] = useState('')
  const [actionStatus, setActionStatus] = useState('')
  const [busyId, setBusyId] = useState<string | number | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [searchNames, setSearchNames] = useState<Record<string, string>>({})
  const [reloadKey, setReloadKey] = useState(0)
  const clientPagination = layout !== 'all' || triage !== 'all' || kind === 'none'
  const requestLimit = clientPagination ? 0 : pageSize
  const requestOffset = clientPagination ? 0 : offset
  const [sort, setSort] = useState<{
    key: 'folder' | 'status' | 'library' | 'system' | 'region'
    dir: 1 | -1
  }>({ key: 'folder', dir: 1 })

  useEffect(() => {
    if (typeof routeState?.linkSuccess !== 'string') return
    setLinkSuccess(routeState.linkSuccess)
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
  }, [location.pathname, location.search, navigate, routeState?.linkSuccess])

  useEffect(() => {
    getJson('/api/get_libraries')
      .then((value) => {
        const source = Array.isArray(value) ? value : []
        setLibraries(
          source
            .map((row: any) => ({
              uuid: String(row.uuid || ''),
              name: String(row.name || ''),
              platform: String(row.platform_name || row.platform || ''),
            }))
            .filter((row: LibraryOption) => row.uuid),
        )
      })
      .catch(() => setLibraries([]))
  }, [])

  useEffect(() => {
    getJson('/api/unmatched/bad_match_reasons')
      .then((value) => setBadMatchReasons(Array.isArray(value?.reasons) ? value.reasons : []))
      .catch(() => setBadMatchReasons([]))
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => setSearchQuery(query.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    const params = new URLSearchParams({ status, paginate: clientPagination ? '0' : '1' })
    if (!clientPagination) {
      params.set('limit', String(requestLimit))
      params.set('offset', String(requestOffset))
    }
    if (libraryUuid) params.set('library_uuid', libraryUuid)
    if (platform) params.set('platform', platform)
    if (region) params.set('rom_region', region)
    if (searchQuery) params.set('q', searchQuery)
    if (why !== 'all') params.set('why', why)
    if (kind !== 'all' && kind !== 'none') params.set('suggested_kind', kind)
    void getJson(`/api/unmatched_folders?${params}`, { signal: controller.signal })
      .then((value: PageResult) => {
        if (Array.isArray(value)) {
          setRows(value)
          setTotal(value.length)
        } else {
          setRows(Array.isArray(value?.items) ? value.items : [])
          setTotal(Number(value?.total) || 0)
        }
        setError(null)
      })
      .catch((reason) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setError(reason)
        setRows([])
        setTotal(0)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [
    status,
    libraryUuid,
    platform,
    region,
    searchQuery,
    why,
    kind,
    clientPagination,
    requestLimit,
    requestOffset,
    reloadKey,
  ])

  const systems = useMemo(
    () => [...new Set(libraries.map((row) => row.platform).filter(Boolean))].sort(),
    [libraries],
  )
  const filteredRows = useMemo(() => {
    const filtered = rows.filter((row) => {
      const rowKind =
        String(row.suggested_kind || '')
          .trim()
          .toLowerCase() || 'none'
      if (kind !== 'all' && rowKind !== kind) return false
      const leafType = detectLeafType(row.folder_path)
      if (layout !== 'all' && leafType !== layout) return false
      const mismatch = detectPlatformMismatch(row.folder_path, row.library_name, row.platform_name)
      const garbage = isGarbageScaffolding(row)
      if (triage === 'platform-mismatch' && !mismatch) return false
      if (triage === 'garbage' && !garbage) return false
      return true
    })
    const key = sort.key
    return filtered.sort((left, right) => {
      const a = String(
        key === 'folder'
          ? left.folder_path
          : key === 'status'
            ? left.status
            : key === 'library'
              ? left.library_name
              : key === 'system'
                ? left.platform_name
                : left.rom_region || '',
      )
      const b = String(
        key === 'folder'
          ? right.folder_path
          : key === 'status'
            ? right.status
            : key === 'library'
              ? right.library_name
              : key === 'system'
                ? right.platform_name
                : right.rom_region || '',
      )
      return a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true }) * sort.dir
    })
  }, [rows, kind, layout, triage, sort])

  const visibleRows = useMemo(
    () => (clientPagination ? filteredRows.slice(offset, offset + pageSize) : filteredRows),
    [clientPagination, filteredRows, offset, pageSize],
  )
  const displayTotal = clientPagination ? filteredRows.length : total

  useEffect(() => {
    setSelectedIds((current) => {
      const visible = new Set(visibleRows.map((row) => String(row.id)))
      const next = new Set([...current].filter((id) => visible.has(id)))
      return next.size === current.size ? current : next
    })
  }, [visibleRows])

  function changeFilter(setter: (value: string) => void, value: string) {
    setter(value)
    setOffset(0)
  }

  async function runRowAction(row: UnmatchedRow, action: 'merge' | 'keep' | 'ignore') {
    setBusyId(row.id)
    setActionStatus('')
    try {
      await postJson(`/api/unmatched_folders/${encodeURIComponent(String(row.id))}/fix`, { action })
      setActionStatus(
        action === 'merge'
          ? 'Duplicate entry merged.'
          : action === 'keep'
            ? 'Entry returned to Unmatched.'
            : 'Entry ignored.',
      )
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  function toggleSelected(id: string | number) {
    setSelectedIds((current) => {
      const next = new Set(current)
      const key = String(id)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function runBatchAction(
    action: 'clear' | 'ignore_selected' | 'mark_kind' | 'merge' | 'keep' | 'ignore',
    kindValue?: string,
  ) {
    const ids = visibleRows.map((row) => String(row.id)).filter((id) => selectedIds.has(id))
    if (!ids.length) return
    if (action === 'clear' && !window.confirm(`Clear ${ids.length} selected unmatched entries?`))
      return
    if (action === 'ignore_selected' && !window.confirm(`Ignore ${ids.length} selected entries?`))
      return
    setLoading(true)
    setActionStatus('')
    try {
      const chunks: string[][] = []
      for (let index = 0; index < ids.length; index += 100)
        chunks.push(ids.slice(index, index + 100))
      if (action === 'clear') {
        let cleared = 0
        for (const batch of chunks) {
          const result = await postJson('/api/unmatched_folders/batch/clear', { ids: batch })
          cleared += Number(result?.cleared) || 0
        }
        setActionStatus(`Cleared ${cleared} selected entries.`)
      } else if (action === 'ignore_selected') {
        const eligible = visibleRows.filter(
          (row) => ids.includes(String(row.id)) && row.status !== 'Ignore',
        )
        let ignored = 0
        for (let index = 0; index < eligible.length; index += 100) {
          const results = await Promise.all(
            eligible.slice(index, index + 100).map(async (row) => {
              const response = await fetch(
                `/toggle_ignore_status/${encodeURIComponent(String(row.id))}`,
                {
                  method: 'POST',
                  credentials: 'same-origin',
                  headers: csrfHeaders({
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                  }),
                  body: JSON.stringify({}),
                },
              )
              return response.ok
            }),
          )
          ignored += results.filter(Boolean).length
        }
        setActionStatus(`Ignored ${ignored} of ${eligible.length} selected entries.`)
      } else if (action === 'mark_kind' && kindValue) {
        let marked = 0
        for (const batch of chunks) {
          const result = await postJson('/api/unmatched_folders/batch/mark_kind', {
            ids: batch,
            item_kind: kindValue,
          })
          marked += Number(result?.marked) || 0
        }
        setActionStatus(`Marked ${marked} of ${ids.length} selected as ${kindValue}.`)
      } else {
        const duplicateIds = visibleRows
          .filter((row) => ids.includes(String(row.id)) && row.status === 'Duplicate')
          .map((row) => String(row.id))
        if (!duplicateIds.length) {
          setActionStatus('Select duplicate rows for Merge, Keep, or Ignore.')
          return
        }
        let fixed = 0
        for (let index = 0; index < duplicateIds.length; index += 100) {
          const result = await postJson('/api/unmatched_folders/batch/fix', {
            ids: duplicateIds.slice(index, index + 100),
            action,
          })
          fixed += Number(result?.fixed) || 0
        }
        setActionStatus(`Duplicate ${action}: ${fixed} of ${duplicateIds.length}.`)
      }
      setSelectedIds(new Set())
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setLoading(false)
    }
  }

  async function clearRows(statusFilter: 'all' | 'Unmatched') {
    const label = statusFilter === 'all' ? 'all unmatched-folder entries' : 'all Unmatched entries'
    if (
      !window.confirm(
        `Clear ${label}? This removes the database entries only; it does not delete files from storage.`,
      )
    )
      return
    setLoading(true)
    setError(null)
    setActionStatus('')
    let cleared = 0
    try {
      while (true) {
        const params = new URLSearchParams({
          status: statusFilter,
          limit: '100',
          offset: '0',
          paginate: '1',
          include: 'columns',
        })
        const result = await getJson(`/api/unmatched_folders?${params}`)
        const ids = Array.isArray(result?.items)
          ? result.items.map((row: UnmatchedRow) => String(row.id))
          : []
        if (!ids.length) break
        const batch = await postJson('/api/unmatched_folders/batch/clear', { ids })
        const removed = Number(batch?.cleared) || 0
        if (!removed)
          throw new Error('No entries were cleared; stopping to avoid repeating the request.')
        cleared += removed
      }
      setSelectedIds(new Set())
      setActionStatus(`Cleared ${cleared} entries. Storage files were not changed.`)
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setLoading(false)
    }
  }

  async function toggleIgnore(row: UnmatchedRow) {
    setBusyId(row.id)
    setError(null)
    try {
      const response = await fetch(`/toggle_ignore_status/${encodeURIComponent(String(row.id))}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders({
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        }),
        body: JSON.stringify({}),
      })
      if (!response.ok) throw new Error('Unable to change the folder status.')
      const payload = await response.json()
      setActionStatus(payload?.data?.message || payload?.message || 'Folder status updated.')
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function markKind(row: UnmatchedRow, kindValue: string, label: string) {
    setBusyId(row.id)
    setError(null)
    try {
      await postJson(`/api/unmatched_folders/${encodeURIComponent(String(row.id))}/mark_kind`, {
        item_kind: kindValue,
        name: row.search_name || undefined,
      })
      setActionStatus(`Marked as ${label}.`)
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function saveSearchName(row: UnmatchedRow) {
    const id = String(row.id)
    const value = (
      searchNames[id] ??
      row.search_name ??
      row.folder_name ??
      row.folder_path?.split(/[\\/]/).filter(Boolean).at(-1) ??
      ''
    ).trim()
    if (!value) {
      setActionStatus('Enter a search name.')
      return
    }
    setBusyId(row.id)
    setError(null)
    try {
      await postJson(`/api/unmatched_folders/${encodeURIComponent(id)}/name`, {
        search_name: value,
        display_name: value,
      })
      setActionStatus('Search name saved for Fix search. The folder on disk was not renamed.')
      setReloadKey((current) => current + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function retryMatch(row: UnmatchedRow) {
    setBusyId(row.id)
    setError(null)
    try {
      const result = await postJson(
        `/api/unmatched_folders/${encodeURIComponent(String(row.id))}/retry_match`,
        {},
      )
      setActionStatus(
        result?.matched
          ? `Matched ${result.name || result.search_name || 'game'} using current metadata providers.`
          : `No unique metadata match found for ${result.search_name || 'folder'}.`,
      )
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function placeUpdate(row: UnmatchedRow) {
    const targetName = window.prompt(
      'Move this update into the game folder named:',
      row.suggested_search_name || '',
    )
    if (targetName === null) return
    if (!targetName.trim()) {
      setActionStatus('Enter the game folder name.')
      return
    }
    setBusyId(row.id)
    setError(null)
    try {
      const result = await postJson(
        `/api/unmatched_folders/${encodeURIComponent(String(row.id))}/place_update`,
        { game_root_name: targetName.trim() },
      )
      setActionStatus(
        result?.created_game_root
          ? `Created ${result.game_root_name} and moved the update into it.`
          : `Moved the update into ${result.game_root_name || targetName.trim()}.`,
      )
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function saveBadMatch(row: UnmatchedRow, reason: string) {
    let note: string | undefined
    if (reason === 'other') {
      const answer = window.prompt('What is wrong with this match?')
      if (answer === null || !answer.trim()) return
      note = answer.trim()
    }
    setBusyId(row.id)
    setError(null)
    try {
      await postJson(`/api/unmatched/${encodeURIComponent(String(row.id))}/bad_match`, {
        reason: reason || null,
        note,
      })
      setActionStatus(reason ? 'Bad-match feedback saved.' : 'Bad-match feedback cleared.')
      setReloadKey((value) => value + 1)
    } catch (cause) {
      setError(cause)
    } finally {
      setBusyId(null)
    }
  }

  async function deleteFolderFromDisk(row: UnmatchedRow) {
    const folderPath = String(row.folder_path || '')
    if (!window.confirm(`Are you sure you want to delete the folder ${folderPath} FROM DISK?`))
      return
    setBusyId(row.id)
    setError(null)
    try {
      const result = await postJson('/delete_folder', { folder_path: folderPath })
      setActionStatus(result?.message || 'Item deleted successfully. Database entry removed.')
      setReloadKey((value) => value + 1)
    } catch (reason) {
      const failure = reason as { status?: number; message?: string }
      if (
        failure.status === 404 &&
        /specified path does not exist/i.test(String(failure.message || ''))
      ) {
        setActionStatus('The path is already missing; its unmatched entry was removed.')
        setReloadKey((value) => value + 1)
      } else {
        setError(reason)
      }
    } finally {
      setBusyId(null)
    }
  }

  function toggleSort(key: typeof sort.key) {
    setSort((current) => ({ key, dir: current.key === key ? (current.dir === 1 ? -1 : 1) : 1 }))
  }

  const start = displayTotal ? offset + 1 : 0
  const end = Math.min(offset + visibleRows.length, displayTotal)

  return (
    <Page
      title="Unmatched folders"
      lede="Review unmatched folders and duplicate candidates from scan management."
    >
      <div className="od-scan-unmatched__toolbar">
        <div className="od-scan-unmatched__links">
          <a href="/admin/scan-jobs">Return to scan jobs</a>
          <a
            href={`/api/unmatched_folders/export?${new URLSearchParams({ status, format: 'csv', ...(libraryUuid ? { library_uuid: libraryUuid } : {}), ...(platform ? { platform } : {}), ...(region ? { rom_region: region } : {}), ...(searchQuery ? { q: searchQuery } : {}), ...(why !== 'all' ? { why } : {}), ...(kind !== 'all' && kind !== 'none' ? { suggested_kind: kind } : {}) })}`}
          >
            Export CSV
          </a>
          <a
            href={`/api/unmatched_folders/export?${new URLSearchParams({ status, format: 'json', ...(libraryUuid ? { library_uuid: libraryUuid } : {}), ...(platform ? { platform } : {}), ...(region ? { rom_region: region } : {}), ...(searchQuery ? { q: searchQuery } : {}), ...(why !== 'all' ? { why } : {}), ...(kind !== 'all' && kind !== 'none' ? { suggested_kind: kind } : {}) })}`}
          >
            Export JSON
          </a>
        </div>
        <div className="od-scan-unmatched__actions">
          <Button type="button" disabled={loading} onClick={() => void clearRows('Unmatched')}>
            Clear Unmatched
          </Button>
          <Button
            type="button"
            disabled={loading}
            className="od-btn od-btn--danger"
            onClick={() => void clearRows('all')}
          >
            Clear All
          </Button>
          <Button
            type="button"
            disabled={loading}
            onClick={() => setReloadKey((value) => value + 1)}
          >
            Refresh
          </Button>
          <Button
            type="button"
            disabled={loading}
            onClick={async () => {
              try {
                const result = await postJson('/api/unmatched_folders/reclassify_duplicates', {})
                setActionStatus(`Fixed ${Number(result.changed_count) || 0} false duplicates.`)
                setReloadKey((value) => value + 1)
              } catch (reason) {
                setError(reason)
              }
            }}
          >
            Fix false duplicates
          </Button>
          <Button
            type="button"
            disabled={loading}
            onClick={async () => {
              try {
                const result = await postJson('/api/unmatched_folders/backfill_suggested_kind', {})
                setActionStatus(
                  `Kind hints updated ${Number(result.updated) || 0} of ${Number(result.scanned) || 0} scanned.`,
                )
                setReloadKey((value) => value + 1)
              } catch (reason) {
                setError(reason)
              }
            }}
          >
            Backfill kind hints
          </Button>
        </div>
      </div>
      {linkSuccess ? (
        <PageStatus announcement="status" className="od-scan-unmatched__success">
          {linkSuccess}
        </PageStatus>
      ) : null}
      {actionStatus ? <PageStatus announcement="status">{actionStatus}</PageStatus> : null}
      <PageStatus
        loading={loading}
        loadingMessage="Loading unmatched folders…"
        error={error}
        errorMessage="Unable to load unmatched folders."
      />
      <section className="od-scan-unmatched" aria-label="Unmatched folder filters and results">
        <div className="od-scan-unmatched__filter-group" role="group" aria-label="Status filter">
          {STATUS_FILTERS.map(([value, label]) => (
            <Button
              key={value}
              type="button"
              aria-pressed={status === value}
              className={`od-scan-unmatched__filter${status === value ? ' is-active' : ''}`}
              onClick={() => changeFilter(setStatus, value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <label className="od-scan-unmatched__search">
          Search
          <input
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setOffset(0)
            }}
            placeholder="Path, folder, library, platform, or matched title"
          />
        </label>
        <div className="od-scan-unmatched__selects">
          <label>
            Library
            <select
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
            Rows per page
            <select
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
                className={`od-scan-unmatched__filter${layout === value ? ' is-active' : ''}`}
                onClick={() => setLayout(value)}
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
                className={`od-scan-unmatched__filter${triage === value ? ' is-active' : ''}`}
                onClick={() => setTriage(value)}
              >
                {label}
              </Button>
            ))}
          </div>
          <label>
            Why
            <select value={why} onChange={(event) => changeFilter(setWhy, event.target.value)}>
              {WHY_FILTERS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Kind
            <select value={kind} onChange={(event) => changeFilter(setKind, event.target.value)}>
              <option value="all">All kinds</option>
              <option value="experience">Soft title</option>
              <option value="emulator">Emulator</option>
              <option value="tool">Utility</option>
              <option value="none">No hint</option>
            </select>
          </label>
        </div>
        <div className="od-scan-unmatched__pager">
          <span>
            Showing {start}–{end} of {displayTotal}
          </span>
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
        </div>
        {selectedIds.size ? (
          <div
            className="od-scan-unmatched__batch"
            role="group"
            aria-label="Selected folder actions"
          >
            <span>{selectedIds.size} selected</span>
            <Button type="button" disabled={loading} onClick={() => void runBatchAction('clear')}>
              Clear selected
            </Button>
            <Button
              type="button"
              disabled={loading}
              onClick={() => void runBatchAction('ignore_selected')}
            >
              Ignore selected
            </Button>
            <Button
              type="button"
              disabled={loading}
              onClick={() => void runBatchAction('mark_kind', 'experience')}
            >
              Mark Soft
            </Button>
            <Button
              type="button"
              disabled={loading}
              onClick={() => void runBatchAction('mark_kind', 'emulator')}
            >
              Mark Emulator
            </Button>
            <Button
              type="button"
              disabled={loading}
              onClick={() => void runBatchAction('mark_kind', 'tool')}
            >
              Mark Utility
            </Button>
            <Button type="button" disabled={loading} onClick={() => void runBatchAction('merge')}>
              Merge duplicates
            </Button>
            <Button type="button" disabled={loading} onClick={() => void runBatchAction('keep')}>
              Keep duplicates
            </Button>
            <Button type="button" disabled={loading} onClick={() => void runBatchAction('ignore')}>
              Ignore duplicates
            </Button>
            <Button type="button" onClick={() => setSelectedIds(new Set())}>
              Deselect
            </Button>
          </div>
        ) : null}
        <div
          className="od-scan-unmatched__table-wrap"
          tabIndex={0}
          aria-label="Unmatched folders table"
        >
          <table className="od-scan-unmatched__table">
            <thead>
              <tr>
                <th scope="col">
                  <input
                    type="checkbox"
                    aria-label="Select visible folders"
                    checked={
                      visibleRows.length > 0 &&
                      visibleRows.every((row) => selectedIds.has(String(row.id)))
                    }
                    onChange={(event) =>
                      setSelectedIds((current) => {
                        const next = new Set(current)
                        visibleRows.forEach((row) =>
                          event.target.checked
                            ? next.add(String(row.id))
                            : next.delete(String(row.id)),
                        )
                        return next
                      })
                    }
                  />
                </th>
                {(
                  [
                    ['folder', 'Folder'],
                    ['status', 'Status'],
                    ['library', 'Library'],
                    ['system', 'System'],
                    ['region', 'Region'],
                  ] as const
                ).map(([key, label]) => (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={
                      sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'
                    }
                  >
                    <Button
                      type="button"
                      className="od-scan-unmatched__sort"
                      onClick={() => toggleSort(key)}
                    >
                      {label}
                      {sort.key === key ? (sort.dir === 1 ? ' ↑' : ' ↓') : ''}
                    </Button>
                  </th>
                ))}
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select folder ${row.folder_path || row.id}`}
                      checked={selectedIds.has(String(row.id))}
                      onChange={() => toggleSelected(row.id)}
                    />
                  </td>
                  <td className="od-scan-unmatched__path">
                    <span>{row.folder_path || 'Unknown path'}</span>
                    <label
                      className="od-scan-unmatched__name-label"
                      htmlFor={`unmatched-name-${row.id}`}
                    >
                      Search name
                    </label>
                    <div className="od-scan-unmatched__name-edit">
                      <input
                        id={`unmatched-name-${row.id}`}
                        type="text"
                        value={
                          searchNames[String(row.id)] ??
                          row.search_name ??
                          row.folder_name ??
                          row.folder_path?.split(/[\\/]/).filter(Boolean).at(-1) ??
                          ''
                        }
                        onChange={(event) =>
                          setSearchNames((current) => ({
                            ...current,
                            [String(row.id)]: event.target.value,
                          }))
                        }
                        title="Search name for Fix search; does not rename the folder on disk"
                      />
                      <Button
                        type="button"
                        disabled={busyId === row.id}
                        onClick={() => void saveSearchName(row)}
                      >
                        Save name
                      </Button>
                    </div>
                    <div className="od-scan-unmatched__badges">
                      <span>
                        {detectLeafType(row.folder_path) === 'file-leaf' ? 'ROM files' : 'Folder'}
                      </span>
                      {detectPlatformMismatch(
                        row.folder_path,
                        row.library_name,
                        row.platform_name,
                      ) ? (
                        <span>Platform mismatch</span>
                      ) : null}
                      {isGarbageScaffolding(row) ? <span>Garbage</span> : null}
                    </div>
                    {row.why_unmatched ||
                    row.unmatched_reason ||
                    row.match_reason ||
                    row.match_score != null ? (
                      <small className="od-scan-unmatched__why">
                        <strong>Why unmatched?</strong>{' '}
                        {row.why_unmatched ||
                          row.unmatched_reason ||
                          row.match_reason ||
                          'No match reason'}
                        {row.match_score != null ? ` · Match confidence ${row.match_score}` : ''}
                      </small>
                    ) : null}
                    {row.matched_game?.name ? (
                      <small>Matched title: {row.matched_game.name}</small>
                    ) : null}
                    {row.transforms?.length || row.stage_e_candidates?.length ? (
                      <details className="od-scan-unmatched__details">
                        <summary>Match details</summary>
                        {row.transforms?.length ? (
                          <ol>
                            {row.transforms.map((step, index) => (
                              <li key={`${step.stage || 'step'}-${index}`}>
                                <strong>{step.stage || 'Name change'}</strong>{' '}
                                <code>{step.before || ''}</code> → <code>{step.after || ''}</code>
                                {step.reason ? ` · ${step.reason}` : ''}
                              </li>
                            ))}
                          </ol>
                        ) : null}
                        {row.stage_e_candidates?.length ? (
                          <ul>
                            {row.stage_e_candidates.map((candidate, index) => (
                              <li key={`${candidate.source || 'catalog'}-${index}`}>
                                {candidate.name || 'Catalog candidate'}
                                {candidate.source ? ` · ${candidate.source}` : ''}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </details>
                    ) : null}
                  </td>
                  <td>{row.status || 'Unknown'}</td>
                  <td>{row.library_name || '—'}</td>
                  <td>{row.platform_name || '—'}</td>
                  <td>{row.rom_region || '—'}</td>
                  <td>
                    <div className="od-scan-unmatched__row-actions">
                      <Button
                        type="button"
                        onClick={() => setPathModal(String(row.folder_path || ''))}
                      >
                        Open path
                      </Button>
                      <a
                        className="od-btn"
                        href={`/add_game_manual?${new URLSearchParams({ full_disk_path: String(row.folder_path || ''), library_uuid: String(row.library_uuid || ''), from_unmatched: 'true' })}`}
                      >
                        Fix search
                      </a>
                      {row.status === 'Unmatched' ||
                      row.status === 'Pending' ||
                      row.status === 'Duplicate' ? (
                        <>
                          <Button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void markKind(row, 'experience', 'Soft title')}
                          >
                            Mark Soft
                          </Button>
                          <Button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void markKind(row, 'emulator', 'Emulator')}
                          >
                            Mark Emu
                          </Button>
                          <Button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void markKind(row, 'tool', 'Utility')}
                          >
                            Mark Util
                          </Button>
                        </>
                      ) : null}
                      {row.status === 'Unmatched' ? (
                        row.is_bare_update_package ? (
                          <Button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void placeUpdate(row)}
                          >
                            Place update
                          </Button>
                        ) : (
                          <Button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void retryMatch(row)}
                          >
                            Retry match
                          </Button>
                        )
                      ) : null}
                      {badMatchReasons.length ? (
                        <label className="od-scan-unmatched__badmatch">
                          Bad match
                          <select
                            aria-label={`Flag bad match for ${row.folder_path || row.id}`}
                            disabled={busyId === row.id}
                            value={row.bad_match_reason || ''}
                            onChange={(event) => void saveBadMatch(row, event.target.value)}
                          >
                            <option value="">Not flagged</option>
                            {badMatchReasons.map((reason) => (
                              <option key={reason.id} value={reason.id}>
                                {reason.label}
                              </option>
                            ))}
                          </select>
                        </label>
                      ) : null}
                      {row.status !== 'Duplicate' ? (
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void toggleIgnore(row)}
                        >
                          {row.status === 'Ignore' ? 'Unignore' : 'Ignore'}
                        </Button>
                      ) : null}
                      {row.status === 'Duplicate' ? (
                        <>
                          <Button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void runRowAction(row, 'merge')}
                          >
                            Merge
                          </Button>
                          <Button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void runRowAction(row, 'keep')}
                          >
                            Keep
                          </Button>
                          <Button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void runRowAction(row, 'ignore')}
                          >
                            Ignore
                          </Button>
                        </>
                      ) : null}
                      <Button
                        type="button"
                        disabled={busyId === row.id}
                        onClick={() => {
                          if (!window.confirm('Remove this entry from the unmatched list?')) return
                          void postJson('/api/unmatched_folders/batch/clear', {
                            ids: [String(row.id)],
                          })
                            .then(() => {
                              setActionStatus('Entry removed successfully.')
                              setReloadKey((value) => value + 1)
                            })
                            .catch(setError)
                        }}
                      >
                        Clear
                      </Button>
                      <Button
                        type="button"
                        className="od-btn od-btn--danger"
                        disabled={busyId === row.id}
                        onClick={() => void deleteFolderFromDisk(row)}
                      >
                        Delete from disk
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && !error && visibleRows.length === 0 ? (
                <tr>
                  <td colSpan={7}>No folders for this filter.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <OpenPathModal
        open={Boolean(pathModal)}
        path={pathModal}
        label="Unmatched folder"
        onClose={() => setPathModal('')}
      />
    </Page>
  )
}
