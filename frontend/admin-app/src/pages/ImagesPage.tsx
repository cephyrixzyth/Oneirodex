import { useCallback, useEffect, useMemo, useState } from 'react'
import { confirmAction } from '@oneirodex/ui'
import { useSearchParams } from 'react-router-dom'
import { deleteJson, getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { ART_STUDIO_SYSTEMS } from '../components/platformSkins'
import {
  BEST_AVAILABLE_POLICY,
  SERVICE_SOURCE_IDS,
  groupByGame,
  type GameHit,
  type ImageRow,
  type LibraryOption,
  type MissingCoverGame,
  type Option,
} from './images/imagesModel'
import { ImagesMissingCoversPanel } from './images/ImagesMissingCoversPanel'
import { ImagesQueuePanel } from './images/ImagesQueuePanel'
import { ImagesSingleTitlePanel } from './images/ImagesSingleTitlePanel'
import { AdminPageActions } from '../components/AdminPageActions'

export function ImagesPage({ embedded = false }: { embedded?: boolean }) {
  const [params, setParams] = useSearchParams()
  const [gameUuid, setGameUuid] = useState(params.get('game') || '')
  const [gameName, setGameName] = useState(params.get('name') || '')
  const [gameQuery, setGameQuery] = useState('')
  const [gameHits, setGameHits] = useState<GameHit[]>([])

  const [statusFilter, setStatusFilter] = useState('pending')
  const [typeFilter, setTypeFilter] = useState('cover')
  const [groupToggle, setGroupToggle] = useState(true)
  const [images, setImages] = useState<ImageRow[]>([])
  const [pathStatus, setPathStatus] = useState<{ error?: string; path?: string } | null>(null)
  const [queueError, setQueueError] = useState('')
  const [queueMsg, setQueueMsg] = useState('')
  const [queueBusy, setQueueBusy] = useState('')
  const [loadingQueue, setLoadingQueue] = useState(true)

  const [missingCovers, setMissingCovers] = useState<MissingCoverGame[]>([])
  const [missingError, setMissingError] = useState('')
  const [libraries, setLibraries] = useState<LibraryOption[]>([])
  const [platforms, setPlatforms] = useState<Option[]>([])
  const [serviceOptions, setServiceOptions] = useState<Option[]>([])
  const [libraryFilter, setLibraryFilter] = useState('')
  const [platformFilter, setPlatformFilter] = useState('')
  const [serviceFilter, setServiceFilter] = useState('')

  const syncGameParam = useCallback(
    (uuid: string, name: string) => {
      setGameUuid(uuid)
      setGameName(name || '')
      const next = new URLSearchParams(params)
      if (uuid) {
        next.set('game', uuid)
        if (name) next.set('name', name)
      } else {
        next.delete('game')
        next.delete('name')
      }
      setParams(next, { replace: true })
    },
    [params, setParams],
  )

  const loadQueue = useCallback(async () => {
    setLoadingQueue(true)
    setQueueError('')
    try {
      const qs = new URLSearchParams({
        page: '1',
        per_page: groupToggle ? '500' : '50',
        status: statusFilter,
        type: typeFilter,
      })
      const data = await getJson(`/admin/api/image_queue_list?${qs}`)
      setImages(Array.isArray(data.images) ? data.images : [])
      setPathStatus(data.image_save_path || null)
    } catch (err) {
      setQueueError(errorText(err) || String(err))
      setImages([])
      setPathStatus(null)
    } finally {
      setLoadingQueue(false)
    }
  }, [statusFilter, typeFilter, groupToggle])

  useEffect(() => {
    loadQueue()
  }, [loadQueue])

  useEffect(() => {
    getJson('/api/get_libraries')
      .then((rows) => setLibraries(Array.isArray(rows) ? rows : []))
      .catch(() => setLibraries([]))
    getJson('/api/library_platforms')
      .then((rows) => {
        if (Array.isArray(rows) && rows.length) {
          setPlatforms(
            rows.map((p) => ({
              id: p.id || p.value || p.name,
              label: p.name || p.id || p.value,
            })),
          )
          return
        }
        setPlatforms(
          ART_STUDIO_SYSTEMS.filter((s) => s.id).map((s) => ({ id: s.id, label: s.label })),
        )
      })
      .catch(() => {
        setPlatforms(
          ART_STUDIO_SYSTEMS.filter((s) => s.id).map((s) => ({ id: s.id, label: s.label })),
        )
      })
    getJson('/api/search_metadata/sources')
      .then((data) => {
        const sources: any[] = Array.isArray(data.sources) ? data.sources : []
        setServiceOptions(
          sources
            .filter((s) => SERVICE_SOURCE_IDS.has(s.id))
            .map((s) => ({ id: s.id, label: s.name || s.id })),
        )
      })
      .catch(() => setServiceOptions([]))
  }, [])

  const loadMissing = useCallback(async () => {
    setMissingError('')
    try {
      const qs = new URLSearchParams({ limit: '200' })
      if (libraryFilter) qs.set('library_uuid', libraryFilter)
      const data = await getJson(`/api/health/library?${qs}`)
      const worst: MissingCoverGame[] = Array.isArray(data.worst) ? data.worst : []
      setMissingCovers(
        worst.filter((g) => (g.issues || []).some((i) => i.code === 'missing_cover')),
      )
    } catch (err) {
      setMissingError(errorText(err) || String(err))
      setMissingCovers([])
    }
  }, [libraryFilter])

  useEffect(() => {
    loadMissing()
  }, [loadMissing])

  const searchGames = useCallback(async () => {
    const q = gameQuery.trim()
    if (!q) {
      setGameHits([])
      return
    }
    try {
      const rows = await getJson(`/api/search?query=${encodeURIComponent(q)}`)
      setGameHits(Array.isArray(rows) ? rows.slice(0, 12) : [])
    } catch {
      setGameHits([])
    }
  }, [gameQuery])

  const groups = useMemo(() => (groupToggle ? groupByGame(images) : null), [groupToggle, images])

  const downloadBatch = async (size: number) => {
    setQueueBusy(`batch-${size}`)
    setQueueMsg('')
    setQueueError('')
    try {
      const result = await postJson('/admin/api/download_images', { batch_size: size })
      setQueueMsg(result.message || `Downloaded ${result.downloaded || 0}`)
      await loadQueue()
    } catch (err) {
      setQueueError(errorText(err) || String(err))
    } finally {
      setQueueBusy('')
    }
  }

  const retryFailed = async () => {
    setQueueBusy('retry')
    setQueueMsg('')
    setQueueError('')
    try {
      const result = await postJson('/admin/api/download_images', { retry_failed: true })
      setQueueMsg(result.message || 'Retry finished')
      if (result.errors?.length) {
        const first = result.errors[0]
        setQueueError(`Sample failure: ${first.error || 'unknown'}`)
      }
      await loadQueue()
    } catch (err) {
      setQueueError(errorText(err) || String(err))
    } finally {
      setQueueBusy('')
    }
  }

  const downloadOne = async (imageId: string) => {
    setQueueBusy(`img-${imageId}`)
    setQueueError('')
    try {
      const result = await postJson('/admin/api/download_images', { image_ids: [imageId] })
      if (result.downloaded > 0) {
        setQueueMsg(result.message || 'Downloaded')
      } else {
        const reason = result.errors?.[0]?.error || result.message || 'unknown reason'
        setQueueError(`Download failed: ${reason}`)
      }
      await loadQueue()
    } catch (err) {
      setQueueError(errorText(err) || String(err))
    } finally {
      setQueueBusy('')
    }
  }

  const removeOne = async (imageId: string) => {
    const ok = await confirmAction({
      title: 'Remove this image from the queue?',
      body: 'The file on disk stays where it is.',
      confirmLabel: 'Remove from queue',
      cancelLabel: 'Keep it',
    })
    if (!ok) return
    setQueueBusy(`del-${imageId}`)
    try {
      await deleteJson(`/admin/api/delete_image/${imageId}`)
      setQueueMsg('Image deleted')
      await loadQueue()
    } catch (err) {
      setQueueError(errorText(err) || String(err))
    } finally {
      setQueueBusy('')
    }
  }

  // FEAT-D3 — generate art for the selected title. Off unless the operator
  // enabled it and configured an endpoint; the 403/502 split tells them which.
  const generateArtwork = async () => {
    if (!gameUuid) {
      setQueueError('Select a game first.')
      return
    }
    setQueueBusy('generate')
    setQueueError('')
    setQueueMsg('')
    try {
      const result = await postJson('/admin/api/artwork/generate', {
        game_uuid: gameUuid,
        image_type: 'cover',
      })
      setQueueMsg(
        `Generated cover for ${gameName || gameUuid}` +
          (result.generated_by ? ` via ${result.generated_by}` : ''),
      )
      await loadQueue()
      await loadMissing()
    } catch (err) {
      setQueueError(
        `${errorText(err) || String(err)} — set ENABLE_AI_ARTWORK and AI_ARTWORK_URL, ` +
          'and start the artwork profile.',
      )
    } finally {
      setQueueBusy('')
    }
  }

  const autoPick = async () => {
    setQueueBusy('autopick')
    setQueueError('')
    setQueueMsg('')
    try {
      const result = await postJson('/admin/api/covers/batch/apply', {
        policy: BEST_AVAILABLE_POLICY,
        missing_cover: true,
        limit_games: 25,
        library_uuid: libraryFilter || undefined,
        platform: platformFilter || undefined,
        service: serviceFilter || undefined,
      })
      if (result.image_save_path?.error) {
        setQueueError(`IMAGE_SAVE_PATH: ${result.image_save_path.error}`)
      }
      const applied = result.applied ?? 0
      const failed = result.failed ?? 0
      setQueueMsg(
        `Auto-pick finished — applied ${applied}, failed ${failed}` +
          (result.policy
            ? ` · policy ${Array.isArray(result.policy) ? result.policy.join('→') : result.policy}`
            : ''),
      )
      if (failed && result.results?.length) {
        const firstFail = result.results.find((r: any) => r.status === 'failed')
        if (firstFail?.error) {
          setQueueError(
            `Sample failure (${firstFail.name || firstFail.game_uuid}): ${firstFail.error}`,
          )
        }
      }
      await loadQueue()
      await loadMissing()
    } catch (err) {
      setQueueError(
        `Auto-pick failed calling POST /admin/api/covers/batch/apply (policy=${BEST_AVAILABLE_POLICY}). ${errorText(err)}`,
      )
    } finally {
      setQueueBusy('')
    }
  }

  const massSearch = async () => {
    setQueueBusy('mass-search')
    setQueueError('')
    setQueueMsg('')
    try {
      const result = await postJson('/admin/api/covers/batch/search', {
        missing_cover: true,
        limit_games: 25,
        library_uuid: libraryFilter || undefined,
        platform: platformFilter || undefined,
        service: serviceFilter || undefined,
      })
      const games = Array.isArray(result.games)
        ? result.games
        : Array.isArray(result.results)
          ? result.results
          : []
      const withHits = games.filter((g: any) => (g.candidates || []).length > 0).length
      setQueueMsg(
        `Mass cover search — ${games.length} title(s), ${withHits} with candidates` +
          (serviceFilter ? ` · service ${serviceFilter}` : ''),
      )
      if (result.errors?.length) {
        setQueueError(`Sample search error: ${result.errors[0].error || 'unknown'}`)
      }
    } catch (err) {
      setQueueError(`Mass search failed (POST /admin/api/covers/batch/search). ${errorText(err)}`)
    } finally {
      setQueueBusy('')
    }
  }

  return (
    <div className={embedded ? 'od-images-embedded' : 'od-admin-page'}>
      {!embedded ? (
        <>
          <h1>Art &amp; images</h1>
          <p className="od-admin-lede">
            Pick artwork for one title and manage pending or failed downloads. The full scan-mgmt
            image table remains available when you need its legacy review controls. Admin only.
          </p>
        </>
      ) : (
        <p className="od-admin-lede">
          Search provider art for one library title, then manage pending/failed downloads in bulk.
        </p>
      )}

      <AdminPageActions label="Image page actions">
        <a className="od-cbtn" href="/scan_management?active_tab=image_queue">
          Full scan-mgmt image table
        </a>
        {!embedded ? (
          <a className="od-cbtn" href="/admin/art_studio">
            Art studio
          </a>
        ) : null}
        <a className="od-cbtn" href="/admin/integrations#steamgriddb">
          SteamGridDB settings
        </a>
      </AdminPageActions>

      <ImagesSingleTitlePanel
        gameHits={gameHits}
        gameName={gameName}
        gameQuery={gameQuery}
        gameUuid={gameUuid}
        loadMissing={loadMissing}
        loadQueue={loadQueue}
        searchGames={searchGames}
        setGameHits={setGameHits}
        setGameQuery={setGameQuery}
        syncGameParam={syncGameParam}
      />

      <ImagesQueuePanel
        autoPick={autoPick}
        downloadBatch={downloadBatch}
        downloadOne={downloadOne}
        gameUuid={gameUuid}
        generateArtwork={generateArtwork}
        groupToggle={groupToggle}
        groups={groups}
        images={images}
        libraries={libraries}
        libraryFilter={libraryFilter}
        loadQueue={loadQueue}
        loadingQueue={loadingQueue}
        massSearch={massSearch}
        pathStatus={pathStatus}
        platformFilter={platformFilter}
        platforms={platforms}
        queueBusy={queueBusy}
        queueError={queueError}
        queueMsg={queueMsg}
        removeOne={removeOne}
        retryFailed={retryFailed}
        serviceFilter={serviceFilter}
        serviceOptions={serviceOptions}
        setGroupToggle={setGroupToggle}
        setLibraryFilter={setLibraryFilter}
        setPlatformFilter={setPlatformFilter}
        setServiceFilter={setServiceFilter}
        setStatusFilter={setStatusFilter}
        setTypeFilter={setTypeFilter}
        statusFilter={statusFilter}
        syncGameParam={syncGameParam}
        typeFilter={typeFilter}
      />

      <ImagesMissingCoversPanel
        missingCovers={missingCovers}
        missingError={missingError}
        syncGameParam={syncGameParam}
      />
    </div>
  )
}
