import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { confirmAction } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { useLibraryScan } from '../hooks/useLibraryScan'
import { errorText } from '../utils/errorText'

type Library = { uuid: string; name: string; last_scan_folder?: string }
type Root = {
  id: string
  label: string
  path: string
  default?: boolean
  exists: boolean
  read: boolean
}
type Folder = { name: string; isDir: boolean }
type GameHit = { uuid: string; name: string; full_disk_path?: string | null }
export type Schedule = '' | '8_hours' | '24_hours' | '48_hours' | 'interval' | 'cron'

export function useScanControls() {
  const { search } = useLocation()
  const query = new URLSearchParams(search)
  const preferredLibraryUuid = query.get('library_uuid') || ''
  const activeTab = query.get('active_tab') || ''
  const manualMode = activeTab === 'manual'
  const [libraries, setLibraries] = useState<Library[]>([])
  const [roots, setRoots] = useState<Root[]>([])
  const [libraryUuid, setLibraryUuid] = useState('')
  const [rootId, setRootId] = useState('')
  const [folder, setFolder] = useState('')
  const [scanMode, setScanMode] = useState<'auto' | 'folders' | 'files'>('auto')
  const [removeMissing, setRemoveMissing] = useState(false)
  const [downloadImages, setDownloadImages] = useState(false)
  const [updateExtras, setUpdateExtras] = useState(false)
  const [fetchHltb, setFetchHltb] = useState(true)
  const [forceHltb, setForceHltb] = useState(false)
  const [schedule, setSchedule] = useState<Schedule>('')
  const [interval, setInterval] = useState(6)
  const [unit, setUnit] = useState<'hours' | 'minutes'>('hours')
  const [cron, setCron] = useState('')
  const [manualRows, setManualRows] = useState<Array<{ name: string; full_path: string }>>([])
  const [manualBusy, setManualBusy] = useState(false)
  const [manualError, setManualError] = useState('')
  const [manualStatus, setManualStatus] = useState('')
  const [manualListed, setManualListed] = useState(false)
  const [manualConflictOpen, setManualConflictOpen] = useState(false)
  const [linkPath, setLinkPath] = useState('')
  const [linkQuery, setLinkQuery] = useState('')
  const [linkHits, setLinkHits] = useState<GameHit[]>([])
  const [linkSelected, setLinkSelected] = useState<GameHit | null>(null)
  const [linkBusy, setLinkBusy] = useState(false)
  const [linkSearching, setLinkSearching] = useState(false)
  const [linkError, setLinkError] = useState('')
  const [linkStatus, setLinkStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [revision, setRevision] = useState(0)
  const [browseOpen, setBrowseOpen] = useState(false)
  const [browsePath, setBrowsePath] = useState('')
  const [browseItems, setBrowseItems] = useState<Folder[]>([])
  const [browseBusy, setBrowseBusy] = useState(false)
  const [browseError, setBrowseError] = useState('')
  const browseTitleId = useId()
  const closeBrowseRef = useRef<HTMLButtonElement | null>(null)
  const { conflictOpen, scanning, startScan, onConflictChoose, onConflictClose } = useLibraryScan()

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError('')
    Promise.all([getJson('/api/get_libraries'), getJson('/api/library_roots')])
      .then(([libraryPayload, rootPayload]) => {
        if (!Array.isArray(libraryPayload) || !Array.isArray(rootPayload.roots)) {
          throw new Error('Scan controls returned an invalid response.')
        }
        const availableLibraries = libraryPayload as Library[]
        const availableRoots = rootPayload.roots as Root[]
        if (!cancelled) {
          setLibraries(availableLibraries)
          setLibraryUuid((current) => {
            if (
              preferredLibraryUuid &&
              availableLibraries.some((library) => library.uuid === preferredLibraryUuid)
            )
              return preferredLibraryUuid
            return availableLibraries.some((library) => library.uuid === current)
              ? current
              : availableLibraries[0]?.uuid || ''
          })
          setRoots(availableRoots)
          setRootId(
            (current) =>
              current ||
              availableRoots.find((root) => root.default)?.id ||
              availableRoots[0]?.id ||
              '',
          )
        }
      })
      .catch((error) => {
        if (!cancelled) setLoadError(errorText(error) || 'Unable to load scan controls.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [preferredLibraryUuid, revision])

  async function browse(path: string, nextRoot = rootId) {
    setBrowseBusy(true)
    setBrowseError('')
    try {
      const query = new URLSearchParams({ root: nextRoot, path })
      const payload = await getJson(`/api/browse_folders_ss?${query}`)
      if (!Array.isArray(payload)) throw new Error('Folder browser returned an invalid response.')
      setRootId(nextRoot)
      setBrowsePath(path)
      setBrowseItems((payload as Folder[]).filter((item) => item.isDir))
    } catch (error) {
      setBrowseError(errorText(error) || 'Unable to browse this scan location.')
    } finally {
      setBrowseBusy(false)
    }
  }

  async function openBrowser() {
    const selectedRoot =
      roots.find((root) => root.id === rootId) || roots.find((root) => root.default) || roots[0]
    if (!selectedRoot) return
    setBrowseOpen(true)
    await browse('', selectedRoot.id)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (loading || loadError || !libraryUuid || scanning) return
    void startScan({
      libraryUuid,
      folder,
      settings: {
        use_library_root: true,
        library_root: rootId,
        scan_mode: scanMode,
        remove_missing: removeMissing,
        download_missing_images: downloadImages,
        force_updates_extras_scan: updateExtras,
        fetch_hltb: fetchHltb,
        force_hltb_refetch: forceHltb,
        schedule,
        schedule_interval_value: interval,
        schedule_interval_unit: unit,
        schedule_cron: cron,
      },
    })
  }

  function invalidateManualPreview() {
    setManualRows([])
    setManualError('')
    setManualStatus('')
    setManualListed(false)
  }

  async function listManualCandidates(queuePolicy: 'inspect' | 'queue' | 'force' = 'inspect') {
    if (!libraryUuid || !rootId || manualBusy) return
    setManualBusy(true)
    setManualError('')
    setManualStatus('')
    setManualListed(false)
    setManualRows([])
    try {
      const payload = await postJson('/api/library_tools/manual_identify/list', {
        library_uuid: libraryUuid,
        root: rootId,
        folder,
        scan_mode: scanMode,
        force_updates_extras_scan: updateExtras,
        fetch_hltb: fetchHltb,
        force_hltb_refetch: forceHltb,
        queue_policy: queuePolicy,
      })
      if (payload.action === 'conflict') {
        setManualConflictOpen(true)
      } else if (payload.action === 'queued' || payload.action === 'started') {
        setManualConflictOpen(false)
        setManualStatus(payload.message || 'Manual scan queued.')
        setManualRows([])
        setManualListed(false)
      } else {
        if (!Array.isArray(payload.games))
          throw new Error('Manual identify returned an invalid response.')
        setManualRows(payload.games as Array<{ name: string; full_path: string }>)
        setManualListed(true)
      }
    } catch (error) {
      setManualError(errorText(error) || 'Unable to list games in this folder.')
    } finally {
      setManualBusy(false)
    }
  }

  function chooseManualConflict(policy: 'queue' | 'force') {
    setManualConflictOpen(false)
    void listManualCandidates(policy)
  }

  async function searchExistingGames() {
    const term = linkQuery.trim()
    if (!term || linkSearching || linkBusy) return
    setLinkSearching(true)
    setLinkError('')
    setLinkStatus('')
    setLinkHits([])
    setLinkSelected(null)
    try {
      const result = await getJson(`/api/admin/games_search?q=${encodeURIComponent(term)}`)
      setLinkHits(Array.isArray(result) ? (result as GameHit[]) : [])
      if (!Array.isArray(result) || !result.length)
        setLinkStatus('No existing games matched that search.')
    } catch (error) {
      setLinkError(errorText(error) || 'Unable to search existing games.')
    } finally {
      setLinkSearching(false)
    }
  }

  async function linkExistingGame() {
    if (!linkPath || !linkSelected || linkBusy) return
    const confirmed = await confirmAction({
      title: 'Link this folder to an existing game?',
      body: [
        `Set ${linkSelected.name} to use this folder path?`,
        linkPath,
        'This updates the game path and removes any matching unmatched-folder row.',
      ],
      confirmLabel: 'Link folder',
      tone: 'neutral',
    })
    if (!confirmed) return
    setLinkBusy(true)
    setLinkError('')
    setLinkStatus('')
    try {
      await postJson('/api/library_tools/link_existing_game', {
        game_uuid: linkSelected.uuid,
        full_disk_path: linkPath,
        library_uuid: libraryUuid,
      })
      const linkedName = linkSelected.name
      setManualRows((previous) => {
        const remaining = previous.filter((row) => row.full_path !== linkPath)
        if (!remaining.length) setManualListed(false)
        return remaining
      })
      setLinkPath('')
      setLinkHits([])
      setLinkSelected(null)
      setLinkStatus(`Linked folder to ${linkedName}.`)
    } catch (error) {
      setLinkError(errorText(error) || 'Unable to link this folder.')
    } finally {
      setLinkBusy(false)
    }
  }

  const activeRoot = roots.find((root) => root.id === rootId)
  const browseParts = browsePath.split('/').filter(Boolean)

  return {
    search,
    query,
    preferredLibraryUuid,
    activeTab,
    manualMode,
    libraries,
    setLibraries,
    roots,
    setRoots,
    libraryUuid,
    setLibraryUuid,
    rootId,
    setRootId,
    folder,
    setFolder,
    scanMode,
    setScanMode,
    removeMissing,
    setRemoveMissing,
    downloadImages,
    setDownloadImages,
    updateExtras,
    setUpdateExtras,
    fetchHltb,
    setFetchHltb,
    forceHltb,
    setForceHltb,
    schedule,
    setSchedule,
    interval,
    setInterval,
    unit,
    setUnit,
    cron,
    setCron,
    manualRows,
    setManualRows,
    manualBusy,
    setManualBusy,
    manualError,
    setManualError,
    manualStatus,
    setManualStatus,
    manualListed,
    setManualListed,
    manualConflictOpen,
    setManualConflictOpen,
    linkPath,
    setLinkPath,
    linkQuery,
    setLinkQuery,
    linkHits,
    setLinkHits,
    linkSelected,
    setLinkSelected,
    linkBusy,
    setLinkBusy,
    linkSearching,
    setLinkSearching,
    linkError,
    setLinkError,
    linkStatus,
    setLinkStatus,
    loading,
    setLoading,
    loadError,
    setLoadError,
    revision,
    setRevision,
    browseOpen,
    setBrowseOpen,
    browsePath,
    setBrowsePath,
    browseItems,
    setBrowseItems,
    browseBusy,
    setBrowseBusy,
    browseError,
    setBrowseError,
    browseTitleId,
    closeBrowseRef,
    conflictOpen,
    scanning,
    startScan,
    onConflictChoose,
    onConflictClose,
    browse,
    openBrowser,
    submit,
    invalidateManualPreview,
    listManualCandidates,
    chooseManualConflict,
    searchExistingGames,
    linkExistingGame,
    activeRoot,
    browseParts,
  }
}
