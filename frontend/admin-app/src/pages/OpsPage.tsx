import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PageStatus } from '@oneirodex/ui'

import { getJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { DashboardBoard } from '../components/DashboardBoard'
import { OpsLogModal } from '../components/OpsLogModal'
import { defaultOpsLayout, OPS_STORAGE_KEY, opsWidgetMins } from '../components/opsLayout'
import { formatScanJobCounters } from '../components/opsWidgets'
import '../ops.css'
import { DETAIL_PANEL_IDS } from './ops/opsColumns'
import { buildOpsWidgets, type OpsDeviceRow } from './ops/opsWidgetMap'

// Re-exported: this used to be defined here, and OpsPage.test.jsx imports it
// from this module. Moving the definition without this would have broken a test
// that has nothing to do with the move.
export { formatScanJobCounters }

/**
 * GET /admin/api/ops/summary and /admin/api/ops/system payloads — same loose
 * Backend field map as DashboardPage's OpsSummary; not fully typed, consumers
 * read defensively with `?.` throughout.
 */
export type OpsSummary = any
export type OpsSystemDetail = any

export function livekitLabel(livekit: OpsSummary) {
  if (!livekit) return 'n/a'
  if (livekit.configured === true) {
    if (livekit.reachable === true) return 'reachable'
    if (livekit.reachable === false) return 'unreachable'
    return 'reachability unavailable'
  }
  if (livekit.enabled === true) return 'enabled · incomplete configuration'
  if (livekit.enabled === false) return 'off'
  return 'unavailable'
}

export function livekitTone(livekit: OpsSummary): 'good' | 'warn' | 'bad' | 'na' {
  if (!livekit) return 'na'
  if (livekit.configured === true) {
    if (livekit.reachable === true) return 'good'
    if (livekit.reachable === false) return 'bad'
    return 'na'
  }
  if (livekit.enabled === true && livekit.configured === false) return 'warn'
  return 'na'
}

export function malwareLabel(malware: OpsSummary) {
  if (!malware || typeof malware.enabled !== 'boolean') return 'unavailable'
  if (!malware.enabled) return 'off'
  if (malware.clamav_reachable === true) return 'on · ClamAV up'
  if (malware.clamav_reachable === false) return 'on · ClamAV down (heuristics only)'
  return 'on · ClamAV status unavailable'
}

export function malwareTone(malware: OpsSummary): 'good' | 'warn' | 'bad' | 'na' {
  if (!malware || typeof malware.enabled !== 'boolean') return 'na'
  if (!malware.enabled) return 'na'
  if (malware.clamav_reachable === true) return 'good'
  if (malware.clamav_reachable === false) return 'warn'
  return 'na'
}

/** Panel id → heading. The ids are the keys of the /admin/api/ops/system
 *  payload, so a panel and its data cannot drift apart. */
export function OpsPage() {
  const [snapshot, setSnapshot] = useState<OpsSummary>(null)
  const [error, setError] = useState<unknown>(null)
  /** Initial mount only — never flash content away on background poll. */
  const [bootLoading, setBootLoading] = useState(true)
  /** Manual Refresh button feedback only. */
  const [manualRefreshing, setManualRefreshing] = useState(false)
  const [systemDetail, setSystemDetail] = useState<OpsSystemDetail>(null)
  const [recentLogs, setRecentLogs] = useState<Record<string, unknown>[] | null>(null)
  const [devices, setDevices] = useState<OpsDeviceRow[] | null>(null)
  const [fullLogOpen, setFullLogOpen] = useState(false)
  const [fullLogEvents, setFullLogEvents] = useState<Record<string, unknown>[] | null>(null)
  const [fullLogLoading, setFullLogLoading] = useState(false)
  const [fullLogError, setFullLogError] = useState<string | null>(null)
  const requestRef = useRef<{ id: number; controller: AbortController | null }>({
    id: 0,
    controller: null,
  })
  const hasSnapshotRef = useRef(false)

  const openFullLog = useCallback(() => {
    setFullLogOpen(true)
    if (window.location.hash !== '#full-log') {
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${window.location.search}#full-log`,
      )
    }
  }, [])

  const closeFullLog = useCallback(() => {
    setFullLogOpen(false)
    if (window.location.hash === '#full-log') {
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
    }
  }, [])

  const loadFullLog = useCallback(() => {
    setFullLogLoading(true)
    setFullLogError(null)
    getJson('/admin/api/ops/logs?limit=200')
      .then((data) => {
        setFullLogEvents(data?.events || [])
        setFullLogLoading(false)
      })
      .catch((err) => {
        setFullLogError(errorText(err) || 'Unable to load events')
        setFullLogLoading(false)
      })
  }, [])

  const refresh = useCallback((source = 'poll') => {
    const isManual = source === 'manual'
    const isBoot = source === 'boot'
    requestRef.current.controller?.abort()
    const controller = new AbortController()
    const id = requestRef.current.id + 1
    requestRef.current = { id, controller }
    if (isManual) setManualRefreshing(true)
    getJson('/admin/api/ops/summary', { signal: controller.signal })
      .then((data) => {
        if (requestRef.current.id !== id || controller.signal.aborted) return
        setSnapshot(data)
        setError(null)
        hasSnapshotRef.current = true
        if (isBoot) setBootLoading(false)
        if (isManual) setManualRefreshing(false)
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return
        if (requestRef.current.id !== id) return
        setError(err)
        if (isBoot || !hasSnapshotRef.current) setBootLoading(false)
        if (isManual) setManualRefreshing(false)
      })
  }, [])

  useEffect(() => {
    let cancelled = false
    getJson('/admin/api/ops/system')
      .then((data) => {
        if (!cancelled) setSystemDetail(data)
      })
      .catch(() => {
        if (!cancelled) setSystemDetail(null)
      })

    getJson('/admin/api/ops/logs?limit=50')
      .then((data) => {
        if (!cancelled) setRecentLogs(data?.events || [])
      })
      .catch(() => {
        if (!cancelled) setRecentLogs(null)
      })

    // TC-4: the device list behind the Companions tile.
    getJson('/admin/api/ops/devices?limit=200')
      .then((data) => {
        if (!cancelled) setDevices(Array.isArray(data?.devices) ? data.devices : [])
      })
      .catch(() => {
        if (!cancelled) setDevices(null)
      })

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    refresh('boot')
    const tick = () => {
      if (document.hidden) return
      refresh('poll')
    }
    const timer = window.setInterval(tick, 15000)
    const onVis = () => {
      if (!document.hidden) refresh('poll')
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVis)
      requestRef.current.controller?.abort()
    }
  }, [refresh])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const shouldOpen = window.location.hash === '#full-log' || params.get('open') === 'full-log'
    if (shouldOpen) openFullLog()
    const onHash = () => {
      if (window.location.hash === '#full-log') openFullLog()
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [openFullLog])

  useEffect(() => {
    if (!fullLogOpen) return undefined
    loadFullLog()
    return undefined
  }, [fullLogOpen, loadFullLog])

  const presentDetailIds = useMemo(
    () => DETAIL_PANEL_IDS.filter((id) => Object.keys(systemDetail?.[id] || {}).length > 0),
    [systemDetail],
  )

  const widgets = useMemo(
    () =>
      buildOpsWidgets({
        snapshot,
        loading: bootLoading && !snapshot,
        unavailable: !snapshot && !bootLoading && Boolean(error),
        presentDetailIds,
        systemDetail,
        recentLogs,
        openFullLog,
        devices,
      }),
    [
      snapshot,
      bootLoading,
      error,
      presentDetailIds,
      systemDetail,
      recentLogs,
      openFullLog,
      devices,
    ],
  )

  const visibleKey = useMemo(
    () =>
      Object.keys(widgets)
        .filter((id) => widgets[id])
        .sort()
        .join('|'),
    [widgets],
  )

  const getDefaultLayout = useCallback(
    () =>
      defaultOpsLayout({
        visibleIds: visibleKey ? visibleKey.split('|') : [],
      }),
    [visibleKey],
  )

  return (
    <div className="od-admin-page od-ops-page">
      <h1 className="od-ops-page__sr-title">Ops</h1>

      <PageStatus
        error={error}
        loading={bootLoading && !snapshot}
        loadingMessage="Loading ops summary…"
      />

      <DashboardBoard
        widgets={widgets}
        storageKey={OPS_STORAGE_KEY}
        defaultLayout={getDefaultLayout}
        minsFn={opsWidgetMins}
        asOf={snapshot?.as_of}
        onRefresh={() => refresh('manual')}
        refreshing={manualRefreshing}
        refreshDisabled={bootLoading}
        layoutLabel="Ops layout"
        statusLabel="Ops controls"
        refreshAriaLabel="Refresh"
        boardAriaLabel="Key metrics"
      />

      <OpsLogModal
        open={fullLogOpen}
        events={fullLogEvents}
        loading={fullLogLoading}
        error={fullLogError}
        onClose={closeFullLog}
        onCleared={() => {
          setFullLogEvents([])
          setRecentLogs([])
          loadFullLog()
        }}
      />
    </div>
  )
}
