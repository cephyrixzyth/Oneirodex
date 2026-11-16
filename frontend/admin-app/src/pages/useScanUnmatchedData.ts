import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { getJson } from '../api/adminApi'
import {
  detectLeafType,
  detectPlatformMismatch,
  isGarbageScaffolding,
} from '../components/unmatchedTriage'
import {
  type BadMatchReason,
  type LibraryApiRow,
  type LibraryOption,
  type PageResult,
  type UnmatchedRow,
} from './scanUnmatchedTypes'

export function useScanUnmatchedData() {
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
  const selectedRows = useRef(new Map<string, UnmatchedRow>())
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
            .map((row: LibraryApiRow) => ({
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
        let nextRows: UnmatchedRow[]
        if (Array.isArray(value)) {
          nextRows = value
          setTotal(nextRows.length)
        } else {
          nextRows = Array.isArray(value?.items) ? value.items : []
          setTotal(Number(value?.total) || 0)
        }
        nextRows.forEach((row) => selectedRows.current.set(String(row.id), row))
        setRows(nextRows)
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
    setSelectedIds(new Set())
    selectedRows.current.clear()
  }, [status, libraryUuid, platform, region, searchQuery, why, kind, layout, triage])

  function changeFilter(setter: (value: string) => void, value: string) {
    setSelectedIds(new Set())
    selectedRows.current.clear()
    setter(value)
    setOffset(0)
  }

  const start = displayTotal ? offset + 1 : 0
  const end = Math.min(offset + visibleRows.length, displayTotal)
  return {
    linkSuccess,
    libraries,
    badMatchReasons,
    loading,
    setLoading,
    error,
    setError,
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
    searchQuery,
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
    pathModal,
    setPathModal,
    actionStatus,
    setActionStatus,
    busyId,
    setBusyId,
    selectedIds,
    setSelectedIds,
    selectedRows,
    searchNames,
    setSearchNames,
    setReloadKey,
    sort,
    setSort,
    systems,
    visibleRows,
    displayTotal,
    changeFilter,
    start,
    end,
  }
}
