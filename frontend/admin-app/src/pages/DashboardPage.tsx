import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PageStatus } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
import { DataTable, type DataTableColumn } from '../components/DataTable'
import { DashboardBoard } from '../components/DashboardBoard'
import { DASHBOARD_OPTIONAL_IDS, DASHBOARD_WIDGET_LABELS } from '../components/dashboardLayout'
import { Page } from '../components/Page'
import {
  BuildTile,
  MeterBar,
  MetricTile,
  OpsStatusBanner,
  companionKindRows,
  companionsTone,
  dbPingTone,
  formatBytes,
  formatLibraryHealthHint,
  formatLibraryHealthValue,
  formatLoadAvg,
  formatReadyz,
  libraryHealthTone,
  na,
  percentHealthTone,
  awakeTone,
  scansActiveTone,
} from '../components/opsWidgets'

/**
 * Dashboard glance tables (UX-C8 · W27-C1). Hand-rolled `od-ops-table` blocks
 * until now, which is why the dashboard's tables did not match the rest of
 * admin. `toolbar={false}` for the same reason as the Ops panels: these row
 * sets are capped at a handful, and a filter box over four errors is chrome
 * standing in front of the thing you came to read.
 */
const DASHBOARD_COMPANION_COLUMNS: DataTableColumn[] = [
  { key: 'kind', label: 'Kind' },
  { key: 'online', label: 'Online', align: 'right' },
  { key: 'registered', label: 'Registered', align: 'right' },
]

const DASHBOARD_SCAN_COLUMNS: DataTableColumn[] = [
  { key: 'library', label: 'Library' },
  { key: 'status', label: 'Status' },
  { key: 'progress', label: 'Progress', align: 'right', render: (job) => `${job.progress ?? 0}%` },
]

const DASHBOARD_ERROR_COLUMNS: DataTableColumn[] = [
  { key: 'event_type', label: 'Type', render: (event) => <code>{event.event_type}</code> },
  { key: 'text', label: 'Message' },
]

/**
 * GET /admin/api/ops/summary payload — loose Backend field map (same host,
 * services, library, scans, issues shape as OpsPage). Not fully typed;
 * consumers read defensively with `?.` throughout.
 */
type OpsSummary = any

export function DashboardPage() {
  const [summary, setSummary] = useState<OpsSummary>(null)
  const [error, setError] = useState<unknown>(null)
  const [bootLoading, setBootLoading] = useState(true)
  const [manualRefreshing, setManualRefreshing] = useState(false)
  const requestRef = useRef<{ id: number; controller: AbortController | null }>({
    id: 0,
    controller: null,
  })
  const hasSummaryRef = useRef(false)

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
        setSummary(data)
        setError(null)
        hasSummaryRef.current = true
        if (isBoot) setBootLoading(false)
        if (isManual) setManualRefreshing(false)
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return
        if (requestRef.current.id !== id) return
        setError(err)
        if (isBoot || !hasSummaryRef.current) setBootLoading(false)
        if (isManual) setManualRefreshing(false)
      })
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

  const library = summary?.library
  const scans = summary?.scans
  const host = summary?.host
  const services = summary?.services
  const issues = summary?.issues
  const disk = host?.disk_games || host?.disk_base
  const severity = issues?.overall || 'good'
  const companions = services?.companions
  const kindRows = companionKindRows(companions?.by_kind)

  const unmatched = library?.unmatched_folders
  const gamesTone =
    unmatched == null
      ? library?.games != null
        ? 'good'
        : 'na'
      : Number(unmatched) > 0
        ? 'warning'
        : 'good'

  const hasErrors = (summary?.recent_errors || []).length > 0

  // Memoised on `summary`: every field below is a pure function of it, so the
  // object only needs to change when a poll actually lands new data. Without this
  // it was a fresh literal on every render — every PageStatus ellipsis tick and
  // every parent re-render rebuilt all ~14 elements and, via DashboardBoard's
  // effect, re-ran a layout measure + ResizeObserver teardown.
  const widgets = useMemo(
    () => ({
      status: <OpsStatusBanner severity={severity} items={issues?.items} ariaLabel="Health" />,
      'm-build': <BuildTile build={summary?.build} />,
      'm-libraries': (
        <MetricTile
          label="Libraries"
          value={na(library?.libraries)}
          hint="folders"
          tone={library?.libraries != null ? 'info' : 'na'}
        />
      ),
      'm-games': (
        <MetricTile
          label="Games"
          value={na(library?.games)}
          hint={
            library?.unmatched_folders != null
              ? `${library.unmatched_folders} unmatched`
              : 'catalogue'
          }
          tone={gamesTone}
        />
      ),
      'm-health': (
        <MetricTile
          label="Library health"
          value={formatLibraryHealthValue(library?.health)}
          hint={formatLibraryHealthHint(library?.health)}
          tone={libraryHealthTone(library?.health)}
        />
      ),
      'm-scans': (
        <MetricTile
          label="Scans"
          value={na(scans?.active_count)}
          hint={
            (scans?.jobs || [])[0]
              ? `${scans.jobs[0].library || 'job'} · ${scans.jobs[0].progress}%`
              : 'active'
          }
          tone={scansActiveTone(scans?.active_count)}
        />
      ),
      'm-disk': (
        <MetricTile
          label="Disk"
          value={disk?.percent != null ? `${disk.percent}%` : 'n/a'}
          hint="games volume"
          tone={percentHealthTone(disk?.percent)}
        />
      ),
      'm-load': (
        <MetricTile
          label="Load 1/5/15"
          value={formatLoadAvg(host?.load_avg)}
          tone={host?.load_avg ? 'info' : 'na'}
        />
      ),
      'm-rss': (
        <MetricTile
          label="Process RSS"
          value={formatBytes(host?.process?.rss_bytes)}
          hint={host?.process?.pid != null ? `pid ${host.process.pid}` : 'n/a'}
          tone={host?.process?.rss_bytes != null ? 'info' : 'na'}
        />
      ),
      'm-db': (
        <MetricTile
          label="DB ping"
          value={host?.db_ping_ms != null ? `${host.db_ping_ms} ms` : 'n/a'}
          tone={dbPingTone(host?.db_ping_ms)}
        />
      ),
      'm-awake': (
        <MetricTile
          label="Readyz"
          value={formatReadyz(services?.awake)}
          tone={awakeTone(services?.awake)}
        />
      ),
      'm-companions': (
        <MetricTile
          label="Companions"
          value={`${companions?.online ?? 0} / ${companions?.registered ?? 0}`}
          hint={
            kindRows.length
              ? kindRows.map((r) => `${r.kind} ${r.online}/${r.registered}`).join(' · ')
              : 'by kind n/a'
          }
          tone={companionsTone(companions)}
        />
      ),
      // Optional widgets: hidden until added from "Add widget".
      'm-cpu': (
        <MetricTile
          label="CPU"
          value={host?.cpu?.percent != null ? `${host.cpu.percent}%` : 'n/a'}
          hint="host"
          tone={percentHealthTone(host?.cpu?.percent)}
        />
      ),
      'm-memory': (
        <MetricTile
          label="Memory"
          value={host?.memory?.percent != null ? `${host.memory.percent}%` : 'n/a'}
          hint={
            host?.memory
              ? `${formatBytes(host.memory.used)} / ${formatBytes(host.memory.total)}`
              : 'host'
          }
          tone={percentHealthTone(host?.memory?.percent)}
        />
      ),
      'm-unmatched': (
        <MetricTile
          label="Unmatched folders"
          value={na(library?.unmatched_folders)}
          hint="need a match"
          tone={gamesTone}
        />
      ),
      'scan-jobs': (
        <section className="od-ops-panel od-ops-panel--embedded">
          <h2>Active scan jobs</h2>
          {(scans?.jobs || []).length === 0 ? (
            <p className="od-admin-lede">No scans running.</p>
          ) : (
            <DataTable
              columns={DASHBOARD_SCAN_COLUMNS}
              rows={(scans?.jobs || []).slice(0, 6)}
              getRowKey={(job: { id?: string; library?: string }, index?: number) =>
                String(job.id ?? job.library ?? index)
              }
              toolbar={false}
            />
          )}
        </section>
      ),
      host: (
        <section className="od-ops-panel od-ops-panel--embedded">
          <h2>Host meters</h2>
          {!host ? (
            <p className="od-admin-lede">Host data unavailable.</p>
          ) : (
            <div className="od-ops-meters">
              <MeterBar label="CPU" percent={host.cpu?.percent} />
              <MeterBar
                label="Memory"
                percent={host.memory?.percent}
                detail={
                  host.memory
                    ? `${formatBytes(host.memory.used)} / ${formatBytes(host.memory.total)}`
                    : null
                }
              />
              <MeterBar label="Games disk" percent={disk?.percent} />
            </div>
          )}
        </section>
      ),
      companions: (
        <section className="od-ops-panel od-ops-panel--embedded">
          <h2>Companions by kind</h2>
          {kindRows.length === 0 ? (
            <p className="od-admin-lede">
              {companions
                ? `Online ${companions.online ?? 0} / ${companions.registered ?? 0} · last seen 1h ${companions.last_seen?.within_1h ?? 0}`
                : 'n/a'}
            </p>
          ) : (
            <DataTable
              columns={DASHBOARD_COMPANION_COLUMNS}
              rows={kindRows}
              getRowKey={(row) => row.kind}
              toolbar={false}
            />
          )}
        </section>
      ),
      errors: hasErrors ? (
        <section className="od-ops-panel od-ops-panel--embedded">
          <h2>Recent errors</h2>
          <DataTable
            columns={DASHBOARD_ERROR_COLUMNS}
            rows={summary.recent_errors.slice(0, 4)}
            getRowKey={(event) => event.id}
            toolbar={false}
          />
        </section>
      ) : null,
    }),
    [summary],
  )

  return (
    <Page
      title="Dashboard"
      lede="Observability glance — libraries, host pulse, and open issues (~15s). Drag a widget to move it; drag an edge or corner (or use S/M/L/Full) to resize; pin to lock it. Add widget brings back hidden ones; hover refresh for Updated time."
    >
      {/* GT-B33: the shared status block, not two hand-rolled ones.
          The error branch used to be a `.od-admin-alert` div and the loading
          branch a `.od-admin-lede` paragraph — two shapes on one page, neither
          matching the member app, and the error text discarded whatever the
          server actually said in favour of a fixed sentence. PageStatus keeps
          the operator-facing sentence and adds the status/error_code line. */}
      <PageStatus
        loading={bootLoading && !summary}
        error={error}
        errorMessage="Unable to load ops summary. Open System for details."
        onRetry={() => refresh('manual')}
        retryLabel="Retry"
        loadingMessage="Loading dashboard…"
      />

      <DashboardBoard
        widgets={widgets}
        hasErrors={hasErrors}
        widgetLabels={DASHBOARD_WIDGET_LABELS}
        defaultHidden={DASHBOARD_OPTIONAL_IDS}
        asOf={summary?.as_of}
        onRefresh={() => refresh('manual')}
        refreshing={manualRefreshing}
        refreshDisabled={bootLoading}
      />
    </Page>
  )
}
