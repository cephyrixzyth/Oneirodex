import { useEffect, useState } from 'react'
import {
  checkGameFreshness,
  cleanupOrphanVersions,
  fetchGameDetails,
  fetchGameVersions,
} from '../../api/gameDetails'
import { initiateGameDownload } from '../../api/downloads'
import { honestyApiErrorMessage } from '../../utils/playHonesty'
import { showToast } from '../../utils/toast'
import type { VersionActions } from './detailsTypes'

/* Data and action hooks pulled out of GameDetailsPage (v11 cycle, H-D.2). The
 * bodies are the page's own effect and handlers, unchanged; only the state
 * they close over moved with them. */

/** Loads the game and its versions; `retry` re-runs the load. */
export function useGameDetails(gameUuid: string | undefined) {
  const [game, setGame] = useState<any>(null)
  const [versions, setVersions] = useState<any[]>([])
  const [error, setError] = useState<any>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [versionsLoading, setVersionsLoading] = useState(true)

  useEffect(() => {
    if (!gameUuid) {
      return undefined
    }
    const controller = new AbortController()
    let active = true
    setError(null)
    setGame(null)
    setVersionsLoading(true)

    Promise.all([
      fetchGameDetails(gameUuid, { signal: controller.signal }),
      fetchGameVersions(gameUuid, { signal: controller.signal }).catch(() => ({ versions: [] })),
    ])
      .then(([details, versionData]) => {
        if (!active) {
          return
        }
        setGame(details)
        setVersions(Array.isArray(versionData.versions) ? versionData.versions : [])
        setVersionsLoading(false)
      })
      .catch((err: any) => {
        if (active && err.name !== 'AbortError') {
          setError(err)
          setVersionsLoading(false)
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [gameUuid, retryCount])

  return {
    game,
    setGame,
    versions,
    setVersions,
    versionsLoading,
    error,
    setRetryCount,
    retry: () => setRetryCount((n) => n + 1),
  }
}

/** Download a version / cleanup orphan versions, with the busy + status state the buttons read. */
export function useVersionActions({
  game,
  gameUuid,
  setVersions,
}: {
  game: any
  gameUuid: string | undefined
  setVersions: (rows: any[]) => void
}): VersionActions {
  const [busyVersionKey, setBusyVersionKey] = useState<string | null>(null)
  const [versionActionStatus, setVersionActionStatus] = useState<string | null>(null)
  const [cleanupBusy, setCleanupBusy] = useState(false)

  async function handleVersionDownload({ kind = 'base', versionUuid, label }: LooseProps) {
    if (!game?.uuid || busyVersionKey) {
      return
    }
    const versionKey = `download:${kind}:${versionUuid || 'base'}`
    setBusyVersionKey(versionKey)
    setVersionActionStatus(null)
    try {
      await initiateGameDownload(game.uuid, { kind, versionUuid })
      setVersionActionStatus(`${label || 'Download'} ready - opening Downloads`)
      showToast(`${label || 'Download'} ready - opening Downloads`, 'success')
      window.location.assign('/downloads')
    } catch (err: any) {
      const message = honestyApiErrorMessage(err, 'Download failed')
      setVersionActionStatus(message)
      showToast(message, 'error')
    } finally {
      setBusyVersionKey(null)
    }
  }

  async function handleCleanupOrphans() {
    if (!gameUuid || cleanupBusy || !game?.can_cleanup_versions) {
      return
    }
    setCleanupBusy(true)
    setVersionActionStatus(null)
    try {
      const result = await cleanupOrphanVersions(gameUuid)
      const removed = Number(result.removed ?? result.removed_count ?? result.count ?? 0) || 0
      const message =
        result.message ||
        (removed > 0
          ? `Removed ${removed} missing version${removed === 1 ? '' : 's'}`
          : 'No missing versions to remove')
      setVersionActionStatus(message)
      showToast(message, 'success')
      const versionData = await fetchGameVersions(gameUuid).catch(() => ({ versions: [] }))
      setVersions(Array.isArray(versionData.versions) ? versionData.versions : [])
    } catch (err: any) {
      const message =
        err?.status === 404
          ? 'Orphan cleanup is not available on this server yet'
          : err?.message || 'Failed to remove missing versions'
      setVersionActionStatus(message)
      showToast(message, err?.status === 404 ? 'info' : 'error')
    } finally {
      setCleanupBusy(false)
    }
  }

  return {
    busyVersionKey,
    setBusyVersionKey,
    versionActionStatus,
    setVersionActionStatus,
    cleanupBusy,
    handleVersionDownload,
    handleCleanupOrphans,
  }
}

/** The "Check freshness" action; patches the freshness fields onto the loaded game. */
export function useFreshnessCheck({
  gameUuid,
  setGame,
}: {
  gameUuid: string | undefined
  setGame: (update: (prev: any) => any) => void
}) {
  const [freshnessBusy, setFreshnessBusy] = useState(false)
  const [freshnessError, setFreshnessError] = useState<{ message?: string } | null>(null)

  async function handleFreshnessCheck() {
    if (!gameUuid || freshnessBusy) {
      return
    }
    setFreshnessBusy(true)
    setFreshnessError(null)
    try {
      const result = await checkGameFreshness(gameUuid)
      setGame((prev: any) =>
        prev
          ? {
              ...prev,
              freshness_status: result.status || prev.freshness_status,
              freshness_confidence: result.confidence ?? prev.freshness_confidence,
            }
          : prev,
      )
    } catch (err: any) {
      setFreshnessError(err)
      showToast(err?.message || 'Freshness check failed', 'error')
    } finally {
      setFreshnessBusy(false)
    }
  }

  return { freshnessBusy, freshnessError, handleFreshnessCheck }
}
