import { type ReactNode } from 'react'
import { DataTable } from '../../components/DataTable'
import {
  BuildTile,
  LibraryHealthFactors,
  MeterBar,
  MetricTile,
  OpsStatusBanner,
  companionKindRows,
  formatBytes,
  formatLibraryHealthHint,
  formatLibraryHealthValue,
  formatLibraryWatchDetail,
  formatLibraryWatchStatus,
  formatLoadAvg,
  formatReadyz,
  libraryHealthTone,
  na,
  normalizeLibraryHealth,
  booleanTone,
  usageTone,
} from '../../components/opsWidgets'
import {
  COMPANION_KIND_COLUMNS,
  DETAIL_PANELS,
  DEVICE_COLUMNS,
  DetailPanel,
  RECENT_ERROR_COLUMNS,
  SCAN_JOB_COLUMNS,
} from './opsColumns'
import {
  livekitLabel,
  livekitTone,
  malwareLabel,
  malwareTone,
  type OpsSummary,
  type OpsSystemDetail,
} from '../OpsPage'

function ServiceStatus({
  value,
  tone = 'na',
}: {
  value: string
  tone?: 'good' | 'warn' | 'bad' | 'na'
}) {
  return <span className={`od-ops-service-status od-ops-service-status--${tone}`}>{value}</span>
}

/** INSP-44 — first GPU's name and VRAM, or why the tile reads n/a. */
export function gpuHint(gpu: OpsSummary): string {
  const first = gpu?.gpus?.[0]
  if (!first) return 'no NVML or reader'
  const vram =
    first.mem_used != null && first.mem_total != null
      ? ` · ${formatBytes(first.mem_used)} / ${formatBytes(first.mem_total)}`
      : ''
  const temp = first.temp_c != null ? ` · ${first.temp_c}°C` : ''
  const source = gpu.source === 'reader' ? ' (reader)' : ''
  return `${first.name || 'GPU'}${vram}${temp}${source}`
}

function readinessChecks(checks: unknown): ReactNode {
  if (!checks || typeof checks !== 'object' || Array.isArray(checks)) return 'n/a'
  const entries = Object.entries(checks as Record<string, unknown>)
  if (!entries.length) return 'n/a'
  const summary = (value: unknown) => {
    if (value === null) return 'unavailable'
    if (typeof value !== 'object') return String(value)
    const row = value as Record<string, unknown>
    const state = row.status ?? row.state ?? row.result
    if (state != null && typeof state !== 'object') return String(state)
    if (typeof row.ok === 'boolean') return row.ok ? 'passed' : 'failed'
    if (typeof row.healthy === 'boolean') return row.healthy ? 'healthy' : 'unhealthy'
    if (typeof row.reachable === 'boolean') return row.reachable ? 'reachable' : 'unreachable'
    return 'details available'
  }
  return (
    <div className="od-ops-readiness">
      <ul aria-label="Readiness checks">
        {entries.map(([name, value]) => (
          <li key={name}>
            <strong>{name}</strong>
            <span>{summary(value)}</span>
          </li>
        ))}
      </ul>
      <details>
        <summary>View check data</summary>
        <pre>{JSON.stringify(checks, null, 2)}</pre>
      </details>
    </div>
  )
}

export interface OpsDeviceRow {
  device_id: string
  device_kind: string
  device_name?: string | null
  client_version?: string | null
  last_seen_at?: string | null
  user_id?: number
  user_name?: string | null
  online: boolean
}

/* The Ops widget map, moved out of OpsPage's useMemo (v11 cycle, H-D.2). The
 * JSX is unchanged; the values it derives from the snapshot are derived here,
 * so the page's memo can depend on exactly the five things it passes in. */
export function buildOpsWidgets({
  snapshot,
  loading = false,
  unavailable = false,
  presentDetailIds,
  systemDetail,
  recentLogs,
  openFullLog,
  devices = null,
}: {
  snapshot: OpsSummary
  loading?: boolean
  unavailable?: boolean
  presentDetailIds: string[]
  systemDetail: OpsSystemDetail
  recentLogs: Record<string, unknown>[] | null
  openFullLog: () => void
  /** `/admin/api/ops/devices` rows (TC-4); null while loading or unavailable. */
  devices?: OpsDeviceRow[] | null
}): Record<string, ReactNode> {
  const host = snapshot?.host
  const library = snapshot?.library
  const scans = snapshot?.scans
  const services = snapshot?.services
  const issues = snapshot?.issues
  const severity = issues?.overall || 'good'
  const companions = services?.companions
  const kindRows = companionKindRows(companions?.by_kind)
  const lastSeen = companions?.last_seen

  const map: Record<string, ReactNode> = {
    status: (
      <OpsStatusBanner
        severity={severity}
        items={issues?.items}
        ariaLabel="System status"
        loading={loading}
        unavailable={unavailable}
      />
    ),
    'm-cpu': (
      <MetricTile
        label="CPU"
        value={na(host?.cpu?.percent, '%')}
        hint={na(host?.cpu?.cores_logical, ' cores')}
        tone={usageTone(host?.cpu?.percent)}
      />
    ),
    'm-load': <MetricTile label="Load 1/5/15" value={formatLoadAvg(host?.load_avg)} hint="host" />,
    'm-memory': (
      <MetricTile
        label="Memory"
        value={na(host?.memory?.percent, '%')}
        hint={
          host?.memory
            ? `${formatBytes(host.memory.used)} / ${formatBytes(host.memory.total)}`
            : 'n/a'
        }
        tone={usageTone(host?.memory?.percent)}
      />
    ),
    'm-gpu': (
      <MetricTile
        label="GPU"
        value={na(host?.gpu?.gpus?.[0]?.util_percent, '%')}
        hint={gpuHint(host?.gpu)}
        tone={host?.gpu ? usageTone(host.gpu.gpus?.[0]?.util_percent) : 'na'}
      />
    ),
    'm-build': <BuildTile build={snapshot?.build} />,
    'm-rss': (
      <MetricTile
        label="Process RSS"
        value={formatBytes(host?.process?.rss_bytes)}
        hint={host?.process?.pid != null ? `pid ${host.process.pid}` : 'n/a'}
      />
    ),
    'm-db': (
      <MetricTile
        label="DB ping"
        value={host?.db_ping_ms != null ? `${host.db_ping_ms} ms` : 'n/a'}
        hint="SELECT 1"
        tone={usageTone(host?.db_ping_ms, { warn: 50, bad: 250 })}
      />
    ),
    'm-awake': (
      <MetricTile
        label="Readyz"
        value={formatReadyz(services?.awake)}
        hint={na(services?.awake?.http_status)}
        tone={booleanTone(services?.awake == null ? null : services?.awake?.http_status === 200)}
      />
    ),
    'm-companions': (
      <MetricTile
        label="Companions"
        value={`${companions?.online ?? 0} / ${companions?.registered ?? 0}`}
        hint={`${lastSeen?.within_1h ?? 0} in 1h · ${lastSeen?.stale ?? 0} stale`}
      />
    ),
    'm-disk': (
      <MetricTile
        label="Games disk"
        value={na(host?.disk_games?.percent ?? host?.disk_base?.percent, '%')}
        hint="volume use"
        tone={usageTone(host?.disk_games?.percent ?? host?.disk_base?.percent)}
      />
    ),
    'm-watch': (
      <MetricTile
        label="Library watch"
        value={formatLibraryWatchStatus(services?.library_watch)}
        hint={
          services?.library_watch?.enabled
            ? `${services.library_watch.roots ?? 0} roots · ${services.library_watch.pending_libraries ?? 0} pending`
            : 'ONEIRODEX_LIBRARY_WATCH off'
        }
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
    host: (
      <section className="od-ops-panel od-ops-panel--embedded">
        <h2>Host meters</h2>
        {!host ? (
          <p>{snapshot?.host_error || 'Host data unavailable.'}</p>
        ) : (
          <>
            <p className="od-ops-panel__lede">
              <strong>{host.hostname || 'Unknown host'}</strong>
              {' · '}
              {host.os || 'Unknown OS'} · {host.ip || 'No IP'}
              {' · '}
              up {host.uptime_system || 'n/a'} / app {host.uptime_app || 'n/a'}
            </p>
            <div className="od-ops-meters">
              <MeterBar
                label="CPU"
                percent={host.cpu?.percent}
                detail={
                  host.cpu?.cores_logical != null ? `${host.cpu.cores_logical} logical cores` : null
                }
              />
              <MeterBar
                label="Memory"
                percent={host.memory?.percent}
                detail={
                  host.memory
                    ? `${formatBytes(host.memory.used)} / ${formatBytes(host.memory.total)}`
                    : null
                }
              />
              <MeterBar
                label="App disk"
                percent={host.disk_base?.percent}
                detail={
                  host.disk_base
                    ? `${formatBytes(host.disk_base.used)} / ${formatBytes(host.disk_base.total)}`
                    : null
                }
              />
              <MeterBar
                label="Games disk"
                percent={host.disk_games?.percent}
                detail={
                  host.disk_games
                    ? `${formatBytes(host.disk_games.used)} / ${formatBytes(host.disk_games.total)}`
                    : null
                }
              />
            </div>
          </>
        )}
      </section>
    ),
    services: (
      <section className="od-ops-panel od-ops-panel--embedded od-ops-panel--services">
        <h2>Services</h2>
        {!services ? (
          <p>{snapshot?.services_error || 'Services data unavailable.'}</p>
        ) : (
          <>
            <p className="od-ops-panel__scroll-hint">
              Swipe or use arrow keys to view more service details.
            </p>
            <div
              className="od-ops-panel__scroll"
              tabIndex={0}
              role="region"
              aria-label="Services table; scroll horizontally on narrow screens"
            >
              <table className="od-ops-table od-ops-table--services">
                <thead>
                  <tr>
                    <th>Service</th>
                    <th>Status</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Readyz</td>
                    <td>
                      <ServiceStatus
                        value={formatReadyz(services.awake)}
                        tone={
                          services.awake?.status === 'ok'
                            ? 'good'
                            : services.awake?.status
                              ? 'bad'
                              : 'na'
                        }
                      />
                    </td>
                    <td>{readinessChecks(services.awake?.checks)}</td>
                  </tr>
                  <tr>
                    <td>LiveKit</td>
                    <td>
                      <ServiceStatus
                        value={livekitLabel(services.livekit)}
                        tone={livekitTone(services.livekit)}
                      />
                    </td>
                    <td>{services.livekit?.error || '—'}</td>
                  </tr>
                  <tr>
                    <td>Malware</td>
                    <td>
                      <ServiceStatus
                        value={malwareLabel(services.malware)}
                        tone={malwareTone(services.malware)}
                      />
                    </td>
                    <td>
                      {services.malware?.clamav_error || services.malware?.clamav_version || '—'}
                    </td>
                  </tr>
                  <tr>
                    <td>Queues</td>
                    <td>
                      {services.queues?.scans_active ?? 0} active ·{' '}
                      {services.queues?.scans_pending ?? 0} pending
                    </td>
                    <td>{services.queues?.downloads_open ?? 0} downloads open</td>
                  </tr>
                  <tr>
                    <td>Library watch</td>
                    <td>{formatLibraryWatchStatus(services.library_watch)}</td>
                    <td>{formatLibraryWatchDetail(services.library_watch)}</td>
                  </tr>
                  {(services.game_servers?.servers || []).map((server: OpsSummary) => (
                    <tr key={server.uuid || server.display_name}>
                      <td>Game server · {server.display_name || 'unnamed'}</td>
                      <td>
                        <ServiceStatus
                          value={
                            server.reachable === true
                              ? 'reachable'
                              : server.reachable === false
                                ? 'unreachable'
                                : 'unavailable'
                          }
                          tone={
                            server.reachable === true
                              ? 'good'
                              : server.reachable === false
                                ? 'bad'
                                : 'na'
                          }
                        />
                      </td>
                      <td>{server.error || server.method || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    ),
    companions: (
      <section className="od-ops-panel od-ops-panel--embedded">
        <h2>Companions</h2>
        {!companions ? (
          <p>n/a</p>
        ) : (
          <>
            <p className="od-ops-panel__lede">
              Online {companions.online ?? 0} / {companions.registered ?? 0}
              {' · '}
              window {companions.window_minutes ?? 3}m{' · '}
              newest {lastSeen?.newest ? new Date(lastSeen.newest).toLocaleString() : 'n/a'}
              {' · '}
              1h {lastSeen?.within_1h ?? 0} · 24h {lastSeen?.within_24h ?? 0} · stale{' '}
              {lastSeen?.stale ?? 0}
            </p>
            {kindRows.length === 0 ? (
              <p className="od-admin-lede">No registered companions by kind.</p>
            ) : (
              <DataTable
                columns={COMPANION_KIND_COLUMNS}
                rows={kindRows}
                getRowKey={(row) => row.kind}
                toolbar={false}
              />
            )}
            {/* TC-4: which devices, not just how many. A seat appears after its
                first heartbeat with a device_kind; nothing here means none has. */}
            <h3 className="od-ops-panel__subhead">Devices</h3>
            {devices === null ? (
              <p className="od-admin-lede">Device list unavailable.</p>
            ) : devices.length === 0 ? (
              <p className="od-admin-lede">
                No devices have checked in yet. A companion, thin seat or browser shell appears here
                after its first heartbeat.
              </p>
            ) : (
              <DataTable
                columns={DEVICE_COLUMNS}
                rows={devices}
                getRowKey={(row) => `${row.user_id ?? ''}:${row.device_id}`}
                toolbar={false}
              />
            )}
          </>
        )}
      </section>
    ),
    library: (
      <section className="od-ops-panel od-ops-panel--embedded">
        <h2>Library pulse</h2>
        {!library ? (
          <p>{snapshot?.library_error || 'Library data unavailable.'}</p>
        ) : (
          <>
            <div className="od-ops-strip od-ops-strip--compact">
              <MetricTile label="Libraries" value={na(library.libraries)} />
              <MetricTile label="Games" value={na(library.games)} />
              <MetricTile label="Unmatched" value={na(library.unmatched_folders)} />
              <MetricTile label="Open downloads" value={na(library.download_requests_open)} />
              <MetricTile
                label="Health"
                value={formatLibraryHealthValue(library.health)}
                hint={
                  normalizeLibraryHealth(library.health)?.grade ||
                  formatLibraryHealthHint(library.health)
                }
                tone={libraryHealthTone(library.health)}
              />
            </div>
            <LibraryHealthFactors health={library.health} />
          </>
        )}
      </section>
    ),
    scans: (
      <section className="od-ops-panel od-ops-panel--embedded od-ops-panel--wide">
        <h2>Scans</h2>
        {!scans ? (
          <p>{snapshot?.scans_error || 'Scan data unavailable.'}</p>
        ) : (scans.jobs || []).length === 0 ? (
          <p className="od-admin-lede">
            {scans.active_count ?? 0} active
            {scans.queued_count != null ? <> · {scans.queued_count} queued</> : null}
            {' · '}no recent jobs.
          </p>
        ) : (
          <>
            <p className="od-ops-panel__lede">
              {scans.active_count ?? 0} active
              {scans.queued_count != null ? <> · {scans.queued_count} queued</> : null}
            </p>
            <DataTable
              columns={SCAN_JOB_COLUMNS}
              rows={scans.jobs}
              getRowKey={(job) => job.id}
              toolbar={false}
            />
          </>
        )}
      </section>
    ),
    errors: (
      <section className="od-ops-panel od-ops-panel--embedded od-ops-panel--wide">
        <h2>Recent errors</h2>
        {(snapshot?.recent_errors || []).length === 0 ? (
          <p className="od-admin-lede">{snapshot?.recent_errors_error || 'No recent errors.'}</p>
        ) : (
          <DataTable
            columns={RECENT_ERROR_COLUMNS}
            rows={snapshot.recent_errors.slice(0, 8)}
            getRowKey={(event) => event.id}
            toolbar={false}
          />
        )}
      </section>
    ),
  }

  for (const id of presentDetailIds) {
    map[`detail-${id}`] = <DetailPanel title={DETAIL_PANELS[id]} values={systemDetail[id]} />
  }

  if (recentLogs) {
    map['recent-log'] = (
      <section className="od-ops-panel od-ops-panel--embedded od-ops-panel--wide">
        <div className="od-ops-panel__head">
          <h2>Recent log</h2>
          <button type="button" className="od-ops-log__full" onClick={openFullLog}>
            Full log — filter by type, level and text
          </button>
        </div>
        <DataTable
          rows={recentLogs}
          getRowKey={(row) => row.id}
          emptyMessage="No system events recorded yet."
          initialSort={{ key: 'timestamp', dir: 'desc' }}
          dense
          columns={[
            {
              key: 'timestamp',
              label: 'When',
              render: (row) => (row.timestamp ? new Date(row.timestamp).toLocaleString() : '—'),
            },
            { key: 'level', label: 'Level' },
            { key: 'type', label: 'Type' },
            { key: 'text', label: 'Event' },
            {
              key: 'user',
              label: 'User',
              render: (row) => row.user || '—',
            },
          ]}
        />
      </section>
    )
  }

  return map
}
